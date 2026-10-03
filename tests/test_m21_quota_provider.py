import json
import queue
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import QuotaMode, QuotaSource, ResourceClass
from projectctl.core.errors import QuotaError
from projectctl.quota.codex_app_server import (
    CodexAppServerQuotaProvider,
    CodexAppServerSession,
    normalize_rate_limits,
)
from projectctl.quota.manager import QuotaManager
from projectctl.quota.resolver import (
    get_account_quota_provider,
    read_current_quota,
    set_account_quota_provider,
)
from projectctl.schemas.config import QuotaPolicy

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def payload(*, primary_minutes=300, secondary_minutes=10080, allowed=True):
    return {
        "ordinaryUsageAllowed": allowed,
        "rateLimits": {
            "limitId": "codex",
            "primary": {
                "usedPercent": 25,
                "windowDurationMins": primary_minutes,
                "resetsAt": 1791043200,
            },
            "secondary": {
                "usedPercent": 40,
                "windowDurationMins": secondary_minutes,
                "resetsAt": 1791648000,
            },
        },
        "rateLimitsByLimitId": None,
    }


def test_normalizes_windows_by_duration_not_position():
    snap = normalize_rate_limits(
        payload(primary_minutes=10080, secondary_minutes=300),
        account="acct",
        observed_at=NOW,
    )
    assert snap.five_hour.remaining_ratio == pytest.approx(.60)
    assert snap.weekly.remaining_ratio == pytest.approx(.75)
    assert snap.five_hour.source == QuotaSource.OFFICIAL


def test_missing_window_remains_unknown():
    value = payload()
    value["rateLimits"]["secondary"] = None
    snap = normalize_rate_limits(value, account="acct", observed_at=NOW)
    assert snap.five_hour.remaining_ratio == pytest.approx(.75)
    assert snap.weekly.remaining_ratio is None


def test_used_percent_is_validated():
    value = payload()
    value["rateLimits"]["primary"]["usedPercent"] = 120
    with pytest.raises(QuotaError):
        normalize_rate_limits(value, account="acct", observed_at=NOW)


def test_prefers_explicit_codex_bucket_without_inferring_other_names():
    value = payload()
    value["rateLimits"] = {"limitId": None, "primary": None, "secondary": None}
    value["rateLimitsByLimitId"] = {
        "other": {"limitId": "other", "limitName": "Some Model", "primary": None, "secondary": None},
        "codex": payload()["rateLimits"],
    }
    snap = normalize_rate_limits(value, account="acct", observed_at=NOW)
    assert snap.selected_limit_id == "codex"
    assert snap.available_limit_ids == ["codex", "other"]


def test_multi_bucket_without_canonical_codex_fails_closed():
    value = payload()
    value["rateLimits"]["limitId"] = None
    value["rateLimitsByLimitId"] = {
        "opaque": {"limitId": "opaque", "limitName": "Fancy Name", "primary": None, "secondary": None}
    }
    with pytest.raises(QuotaError):
        normalize_rate_limits(value, account="acct", observed_at=NOW)


def test_backend_denial_is_explicit_and_blocks_resources():
    snap = normalize_rate_limits(payload(allowed=False), account="acct", observed_at=NOW)
    state = QuotaManager(QuotaPolicy()).state(snap, now=NOW)
    assert state.ordinary_usage_allowed is False
    assert state.mode == QuotaMode.CRITICAL
    assert not QuotaManager(QuotaPolicy()).eligible_for_resource(ResourceClass.TRIVIAL, state)


class _FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeStdout:
    def __init__(self, messages):
        self.messages = queue.Queue()
        for message in messages:
            self.messages.put(json.dumps(message) + "\n")
        self.messages.put("")

    def readline(self):
        return self.messages.get()


class _FakeProcess:
    def __init__(self, messages):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(messages)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def test_jsonrpc_session_ignores_notifications_and_wrong_ids():
    messages = [
        {"jsonrpc": "2.0", "method": "account/rateLimits/updated", "params": {}},
        {"jsonrpc": "2.0", "id": 99, "result": {"ignored": True}},
        {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "test"}},
        {"jsonrpc": "2.0", "id": 2, "result": payload()},
    ]
    fake = _FakeProcess(messages)
    with CodexAppServerSession(binary="codex", popen_factory=lambda *a, **k: fake) as session:
        result = session.read_rate_limits()
    assert result["ordinaryUsageAllowed"] is True
    assert any('"method":"initialize"' in item for item in fake.stdin.writes)
    assert any('"method":"initialized"' in item for item in fake.stdin.writes)
    assert any('"method":"account/rateLimits/read"' in item for item in fake.stdin.writes)


def test_official_snapshot_is_persisted(tmp_path: Path):
    provider = CodexAppServerQuotaProvider(tmp_path, reader=lambda: payload())
    snap = provider.get_snapshot("acct")
    assert snap.provider == "codex_app_server"

    conn = sqlite3.connect(tmp_path / "state.sqlite")
    try:
        row = conn.execute(
            "SELECT snapshot_json FROM quota_observations WHERE account_id='acct' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert json.loads(row[0])["provider"] == "codex_app_server"


def test_provider_selection_is_account_global(tmp_path: Path, monkeypatch):
    set_account_quota_provider("acct", "codex_app_server", home=tmp_path)
    assert get_account_quota_provider("acct", home=tmp_path) == "codex_app_server"

    monkeypatch.setattr(
        "projectctl.quota.resolver.CodexAppServerQuotaProvider.get_snapshot",
        lambda self, account: normalize_rate_limits(payload(), account=account, observed_at=NOW),
    )
    snap = read_current_quota("acct", home=tmp_path)
    assert snap.provider == "codex_app_server"


def test_provider_failure_returns_stale_unknown_snapshot(tmp_path: Path, monkeypatch):
    set_account_quota_provider("acct", "codex_app_server", home=tmp_path)

    def fail(self, account):
        from projectctl.core.errors import ProviderUnavailableError
        raise ProviderUnavailableError("offline")

    monkeypatch.setattr(
        "projectctl.quota.resolver.CodexAppServerQuotaProvider.get_snapshot",
        fail,
    )
    snap = read_current_quota("acct", home=tmp_path)
    state = QuotaManager(QuotaPolicy(max_snapshot_age_seconds=60)).state(snap, now=NOW)
    assert snap.five_hour.remaining_ratio is None
    assert state.stale is True
