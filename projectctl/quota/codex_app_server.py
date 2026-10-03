from __future__ import annotations

import json
import queue
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO

from projectctl.core.enums import ConfidenceLevel, QuotaSource
from projectctl.core.errors import ProviderUnavailableError, QuotaError
from projectctl.core.time import utc_now
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow

FIVE_HOUR_MINUTES = 300
WEEKLY_MINUTES = 10080


class CodexAppServerSession:
    """Minimal read-only JSON-RPC client for the supported Codex App Server."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        startup_timeout: float = 8.0,
        request_timeout: float = 8.0,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ):
        self.binary = binary
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self._popen_factory = popen_factory
        self._process = None
        self._messages: queue.Queue[dict | None] = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    def __enter__(self):
        binary = self.binary or shutil.which("codex")
        if not binary:
            raise ProviderUnavailableError("Codex executable was not found in PATH.")
        try:
            self._process = self._popen_factory(
                [binary, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                shell=False,
            )
        except OSError as exc:
            raise ProviderUnavailableError(f"Could not start Codex App Server: {exc}") from exc
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise ProviderUnavailableError("Codex App Server did not expose stdio pipes.")

        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            args=(self._process.stdout,),
            daemon=True,
            name="projectctl-codex-app-server-reader",
        )
        self._reader_thread.start()

        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "projectctl",
                    "title": "ProjectCTL",
                    "version": "0.13.0",
                },
                "capabilities": {"experimentalApi": True},
            },
            request_id=1,
            timeout=self.startup_timeout,
        )
        self._notify("initialized")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _read_stdout(self, stream: TextIO) -> None:
        try:
            while True:
                line = stream.readline()
                if line == "":
                    self._messages.put(None)
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    self._messages.put({"_projectctl_malformed": line})
                    continue
                if isinstance(payload, dict):
                    self._messages.put(payload)
        except Exception:
            self._messages.put(None)

    def _send(self, payload: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise ProviderUnavailableError("Codex App Server is not running.")
        try:
            self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProviderUnavailableError("Codex App Server closed its input stream.") from exc

    def _notify(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def _request(
        self,
        method: str,
        params: dict | None = None,
        *,
        request_id: int,
        timeout: float,
    ) -> dict:
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

        while True:
            try:
                message = self._messages.get(timeout=timeout)
            except queue.Empty as exc:
                raise ProviderUnavailableError(
                    f"Timed out waiting for Codex App Server method {method}."
                ) from exc
            if message is None:
                raise ProviderUnavailableError(
                    f"Codex App Server exited before replying to {method}."
                )
            if "_projectctl_malformed" in message:
                raise QuotaError("Codex App Server emitted malformed JSON on stdout.")
            if message.get("id") != request_id:
                # Notifications and responses to unrelated request IDs do not satisfy this call.
                continue
            if "error" in message:
                error = message.get("error")
                raise ProviderUnavailableError(
                    f"Codex App Server method {method} failed: {error}"
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise QuotaError(
                    f"Codex App Server method {method} returned no object result."
                )
            return result

    def read_rate_limits(self) -> dict:
        return self._request(
            "account/rateLimits/read",
            request_id=2,
            timeout=self.request_timeout,
        )

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except OSError:
                pass


def _window_from_payload(raw: object) -> tuple[int, QuotaWindow] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QuotaError("Codex rate-limit window must be an object.")
    duration = raw.get("windowDurationMins")
    if duration is None:
        return None
    if not isinstance(duration, int):
        raise QuotaError("Codex rate-limit windowDurationMins must be an integer.")
    if duration not in {FIVE_HOUR_MINUTES, WEEKLY_MINUTES}:
        return None

    used = raw.get("usedPercent")
    if not isinstance(used, (int, float)) or isinstance(used, bool):
        raise QuotaError("Codex rate-limit usedPercent must be numeric.")
    if not 0 <= float(used) <= 100:
        raise QuotaError("Codex rate-limit usedPercent must be between 0 and 100.")

    reset_at = raw.get("resetsAt")
    reset = None
    if reset_at is not None:
        if not isinstance(reset_at, (int, float)) or isinstance(reset_at, bool):
            raise QuotaError("Codex rate-limit resetsAt must be an epoch timestamp.")
        try:
            reset = datetime.fromtimestamp(float(reset_at), tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise QuotaError("Codex rate-limit resetsAt is invalid.") from exc

    remaining = max(0.0, min(1.0, 1.0 - float(used) / 100.0))
    return duration, QuotaWindow(
        remaining_ratio=remaining,
        reset_at=reset,
        source=QuotaSource.OFFICIAL,
        confidence=ConfidenceLevel.HIGH,
    )


def _select_rate_snapshot(result: dict) -> tuple[dict, str | None, list[str]]:
    buckets = result.get("rateLimitsByLimitId")
    available: list[str] = []
    if buckets is not None and not isinstance(buckets, dict):
        raise QuotaError("rateLimitsByLimitId must be an object or null.")
    if isinstance(buckets, dict):
        available = sorted(str(key) for key in buckets)
        explicit = buckets.get("codex")
        if explicit is not None:
            if not isinstance(explicit, dict):
                raise QuotaError("The canonical codex rate-limit bucket is malformed.")
            return explicit, "codex", available

    legacy = result.get("rateLimits")
    if not isinstance(legacy, dict):
        raise QuotaError("Codex App Server response is missing rateLimits.")

    limit_id = legacy.get("limitId")
    if limit_id is not None and not isinstance(limit_id, str):
        raise QuotaError("rateLimits.limitId must be a string or null.")
    if limit_id not in (None, "codex"):
        raise QuotaError(
            "Codex quota bucket is ambiguous; refusing to infer model applicability."
        )
    if isinstance(buckets, dict) and buckets and limit_id is None:
        raise QuotaError(
            "Multiple quota buckets are present but no canonical codex bucket is identified."
        )
    return legacy, limit_id, available


def normalize_rate_limits(
    result: dict,
    *,
    account: str,
    observed_at: datetime | None = None,
) -> QuotaSnapshot:
    if not isinstance(result, dict):
        raise QuotaError("Codex App Server rate-limit response must be an object.")

    ordinary = result.get("ordinaryUsageAllowed")
    if ordinary is not None and not isinstance(ordinary, bool):
        raise QuotaError("ordinaryUsageAllowed must be true, false, or null.")

    selected, limit_id, available = _select_rate_snapshot(result)
    windows: dict[int, QuotaWindow] = {}
    for key in ("primary", "secondary"):
        item = _window_from_payload(selected.get(key))
        if item is None:
            continue
        duration, window = item
        if duration in windows:
            raise QuotaError(f"Duplicate Codex quota window duration: {duration} minutes.")
        windows[duration] = window

    return QuotaSnapshot(
        provider="codex_app_server",
        account=account,
        observed_at=observed_at or utc_now(),
        five_hour=windows.get(FIVE_HOUR_MINUTES, QuotaWindow()),
        weekly=windows.get(WEEKLY_MINUTES, QuotaWindow()),
        ordinary_usage_allowed=ordinary,
        selected_limit_id=limit_id,
        available_limit_ids=available,
    )


class CodexAppServerQuotaProvider:
    provider = "codex_app_server"

    def __init__(
        self,
        home: Path | None = None,
        *,
        reader: Callable[[], dict] | None = None,
        session_factory: Callable[[], CodexAppServerSession] | None = None,
    ):
        self.home = (home or projectctl_home()).resolve()
        _global_init(self.home)
        self.db_path = self.home / "state.sqlite"
        self._reader = reader
        self._session_factory = session_factory or CodexAppServerSession

    def _read(self) -> dict:
        if self._reader is not None:
            return self._reader()
        with self._session_factory() as session:
            return session.read_rate_limits()

    def get_snapshot(self, account: str) -> QuotaSnapshot:
        result = self._read()
        snapshot = normalize_rate_limits(result, account=account)
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO accounts(account_id, provider, config_json) VALUES (?, ?, '{}')",
                (account, self.provider),
            )
            conn.execute(
                "UPDATE accounts SET provider=? WHERE account_id=?",
                (self.provider, account),
            )
            conn.execute(
                "INSERT INTO quota_observations(account_id, observed_at, snapshot_json) VALUES (?, ?, ?)",
                (account, snapshot.observed_at.isoformat(), payload),
            )
            conn.commit()
        finally:
            conn.close()
        return snapshot
