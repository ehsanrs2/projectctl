from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from projectctl.core.errors import QuotaAdmissionError
from projectctl.core.time import utc_now
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.project.loader import load_project_config
from projectctl.storage.sqlite import connect_db

DEFAULT_ADMISSION_TTL_SECONDS = 300.0
DEFAULT_ADMISSION_HEARTBEAT_SECONDS = 60.0


@dataclass(frozen=True)
class AccountAdmission:
    account_id: str
    project_instance_id: str
    project_id: str
    run_id: str
    lease_owner: str
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise QuotaAdmissionError("Admission timestamps must be timezone-aware.")
    return parsed


def _row_to_admission(row: sqlite3.Row) -> AccountAdmission:
    return AccountAdmission(
        account_id=str(row["account_id"]),
        project_instance_id=str(row["project_instance_id"]),
        project_id=str(row["project_id"]),
        run_id=str(row["run_id"]),
        lease_owner=str(row["lease_owner"]),
        acquired_at=_parse_time(str(row["acquired_at"])),
        heartbeat_at=_parse_time(str(row["heartbeat_at"])),
        expires_at=_parse_time(str(row["expires_at"])),
    )


class AccountAdmissionStore:
    """Account-global admission authority backed by PROJECTCTL_HOME/state.sqlite."""

    def __init__(
        self,
        home: Path | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.home = (home or projectctl_home()).resolve()
        _global_init(self.home)
        self.db_path = self.home / "state.sqlite"
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Admission clock must return a timezone-aware datetime.")
        return value

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        *,
        admission: AccountAdmission,
        event_type: str,
        observed_at: datetime,
        payload: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO execution_admission_events(
                account_id, event_type, observed_at,
                project_instance_id, project_id, run_id, lease_owner, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                admission.account_id,
                event_type,
                observed_at.isoformat(),
                admission.project_instance_id,
                admission.project_id,
                admission.run_id,
                admission.lease_owner,
                json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
            ),
        )

    def get(self, account_id: str) -> AccountAdmission | None:
        conn = connect_db(self.db_path, telemetry=False)
        try:
            row = conn.execute(
                "SELECT * FROM execution_admissions WHERE account_id=?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_admission(row) if row is not None else None

    def acquire(
        self,
        *,
        account_id: str,
        project_instance_id: str,
        project_id: str,
        run_id: str,
        lease_owner: str,
        ttl_seconds: float = DEFAULT_ADMISSION_TTL_SECONDS,
    ) -> AccountAdmission:
        if ttl_seconds <= 0:
            raise ValueError("Admission TTL must be positive.")

        now = self._now()
        expires = now + timedelta(seconds=ttl_seconds)
        conn = connect_db(self.db_path, telemetry=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO accounts(account_id, provider, config_json) "
                "VALUES (?, 'manual', '{}')",
                (account_id,),
            )
            row = conn.execute(
                "SELECT * FROM execution_admissions WHERE account_id=?",
                (account_id,),
            ).fetchone()

            if row is not None:
                current = _row_to_admission(row)
                same_owner = (
                    current.project_instance_id == project_instance_id
                    and current.project_id == project_id
                    and current.run_id == run_id
                    and current.lease_owner == lease_owner
                )
                if same_owner and current.expires_at > now:
                    conn.execute(
                        """
                        UPDATE execution_admissions
                        SET heartbeat_at=?, expires_at=?
                        WHERE account_id=? AND project_instance_id=? AND project_id=?
                          AND run_id=? AND lease_owner=?
                        """,
                        (
                            now.isoformat(),
                            expires.isoformat(),
                            account_id,
                            project_instance_id,
                            project_id,
                            run_id,
                            lease_owner,
                        ),
                    )
                    refreshed = AccountAdmission(
                        account_id=account_id,
                        project_instance_id=project_instance_id,
                        project_id=project_id,
                        run_id=run_id,
                        lease_owner=lease_owner,
                        acquired_at=current.acquired_at,
                        heartbeat_at=now,
                        expires_at=expires,
                    )
                    self._event(
                        conn,
                        admission=refreshed,
                        event_type="reconciled",
                        observed_at=now,
                    )
                    conn.commit()
                    return refreshed

                if current.expires_at > now:
                    raise QuotaAdmissionError(
                        "Quota account "
                        f"{account_id!r} is already admitted to run {current.run_id} "
                        f"for project {current.project_id} until {current.expires_at.isoformat()}."
                    )

                self._event(
                    conn,
                    admission=current,
                    event_type="stale_reclaimed",
                    observed_at=now,
                    payload={"expired_at": current.expires_at.isoformat()},
                )
                conn.execute(
                    "DELETE FROM execution_admissions WHERE account_id=?",
                    (account_id,),
                )

            admission = AccountAdmission(
                account_id=account_id,
                project_instance_id=project_instance_id,
                project_id=project_id,
                run_id=run_id,
                lease_owner=lease_owner,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=expires,
            )
            conn.execute(
                """
                INSERT INTO execution_admissions(
                    account_id, project_instance_id, project_id, run_id,
                    lease_owner, acquired_at, heartbeat_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admission.account_id,
                    admission.project_instance_id,
                    admission.project_id,
                    admission.run_id,
                    admission.lease_owner,
                    admission.acquired_at.isoformat(),
                    admission.heartbeat_at.isoformat(),
                    admission.expires_at.isoformat(),
                ),
            )
            self._event(
                conn,
                admission=admission,
                event_type="acquired",
                observed_at=now,
            )
            conn.commit()
            return admission
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def heartbeat(
        self,
        admission: AccountAdmission,
        *,
        ttl_seconds: float = DEFAULT_ADMISSION_TTL_SECONDS,
    ) -> AccountAdmission:
        if ttl_seconds <= 0:
            raise ValueError("Admission TTL must be positive.")

        now = self._now()
        expires = now + timedelta(seconds=ttl_seconds)
        conn = connect_db(self.db_path, telemetry=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM execution_admissions WHERE account_id=?",
                (admission.account_id,),
            ).fetchone()
            if row is None:
                raise QuotaAdmissionError(
                    f"Admission for quota account {admission.account_id!r} no longer exists."
                )
            current = _row_to_admission(row)
            if (
                current.project_instance_id != admission.project_instance_id
                or current.project_id != admission.project_id
                or current.run_id != admission.run_id
                or current.lease_owner != admission.lease_owner
            ):
                raise QuotaAdmissionError(
                    f"Admission ownership changed for quota account {admission.account_id!r}."
                )
            if current.expires_at <= now:
                raise QuotaAdmissionError(
                    f"Admission expired for quota account {admission.account_id!r}."
                )

            conn.execute(
                """
                UPDATE execution_admissions
                SET heartbeat_at=?, expires_at=?
                WHERE account_id=? AND project_instance_id=? AND project_id=?
                  AND run_id=? AND lease_owner=?
                """,
                (
                    now.isoformat(),
                    expires.isoformat(),
                    admission.account_id,
                    admission.project_instance_id,
                    admission.project_id,
                    admission.run_id,
                    admission.lease_owner,
                ),
            )
            conn.commit()
            return AccountAdmission(
                account_id=admission.account_id,
                project_instance_id=admission.project_instance_id,
                project_id=admission.project_id,
                run_id=admission.run_id,
                lease_owner=admission.lease_owner,
                acquired_at=current.acquired_at,
                heartbeat_at=now,
                expires_at=expires,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self, admission: AccountAdmission) -> bool:
        now = self._now()
        conn = connect_db(self.db_path, telemetry=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM execution_admissions WHERE account_id=?",
                (admission.account_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return False

            current = _row_to_admission(row)
            if (
                current.project_instance_id != admission.project_instance_id
                or current.project_id != admission.project_id
                or current.run_id != admission.run_id
                or current.lease_owner != admission.lease_owner
            ):
                raise QuotaAdmissionError(
                    f"Refusing to release foreign admission for quota account "
                    f"{admission.account_id!r}."
                )

            conn.execute(
                """
                DELETE FROM execution_admissions
                WHERE account_id=? AND project_instance_id=? AND project_id=?
                  AND run_id=? AND lease_owner=?
                """,
                (
                    admission.account_id,
                    admission.project_instance_id,
                    admission.project_id,
                    admission.run_id,
                    admission.lease_owner,
                ),
            )
            self._event(
                conn,
                admission=current,
                event_type="released",
                observed_at=now,
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def events(self, account_id: str) -> list[dict]:
        conn = connect_db(self.db_path, telemetry=False)
        try:
            rows = conn.execute(
                """
                SELECT event_type, observed_at, project_instance_id, project_id,
                       run_id, lease_owner, payload_json
                FROM execution_admission_events
                WHERE account_id=?
                ORDER BY id
                """,
                (account_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "event_type": str(row["event_type"]),
                "observed_at": str(row["observed_at"]),
                "project_instance_id": row["project_instance_id"],
                "project_id": row["project_id"],
                "run_id": row["run_id"],
                "lease_owner": row["lease_owner"],
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]


def project_instance_id(project_root: Path) -> str:
    db_path = project_root.resolve() / ".projectctl" / "state.sqlite"
    conn = connect_db(db_path, telemetry=False)
    try:
        row = conn.execute(
            "SELECT value FROM project_metadata WHERE key='project_instance_id'"
        ).fetchone()
    finally:
        conn.close()
    if row is None or not str(row[0]).strip():
        raise QuotaAdmissionError(
            "Project instance identity is missing; run projectctl init/adopt or repair project state."
        )
    return str(row[0])


class AccountAdmissionLease(AbstractContextManager["AccountAdmissionLease"]):
    """Acquire, heartbeat and release one account-global worker-turn admission."""

    def __init__(
        self,
        store: AccountAdmissionStore,
        *,
        account_id: str,
        project_instance_id: str,
        project_id: str,
        run_id: str,
        lease_owner: str,
        ttl_seconds: float = DEFAULT_ADMISSION_TTL_SECONDS,
        interval_seconds: float = DEFAULT_ADMISSION_HEARTBEAT_SECONDS,
    ):
        if ttl_seconds <= 0:
            raise ValueError("Admission TTL must be positive.")
        if interval_seconds <= 0 or interval_seconds >= ttl_seconds:
            raise ValueError(
                "Admission heartbeat interval must be positive and less than the TTL."
            )
        self.store = store
        self.account_id = account_id
        self.project_instance_id = project_instance_id
        self.project_id = project_id
        self.run_id = run_id
        self.lease_owner = lease_owner
        self.ttl_seconds = ttl_seconds
        self.interval_seconds = interval_seconds
        self.admission: AccountAdmission | None = None
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "AccountAdmissionLease":
        self.admission = self.store.acquire(
            account_id=self.account_id,
            project_instance_id=self.project_instance_id,
            project_id=self.project_id,
            run_id=self.run_id,
            lease_owner=self.lease_owner,
            ttl_seconds=self.ttl_seconds,
        )
        self._thread = threading.Thread(
            target=self._loop,
            name=f"projectctl-admission-{self.account_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                assert self.admission is not None
                self.admission = self.store.heartbeat(
                    self.admission,
                    ttl_seconds=self.ttl_seconds,
                )
            except BaseException as exc:
                self._error = exc
                self._stop.set()
                return

    def assert_healthy(self) -> None:
        if self._error is not None:
            raise QuotaAdmissionError(
                f"Account admission heartbeat failed for {self.account_id}: {self._error}"
            ) from self._error

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(
                timeout=max(1.0, min(5.0, self.interval_seconds + 0.5))
            )
        heartbeat_error = self._error
        release_error: BaseException | None = None
        if self.admission is not None:
            try:
                self.store.release(self.admission)
            except BaseException as release_exc:
                release_error = release_exc

        if heartbeat_error is not None:
            raise QuotaAdmissionError(
                f"Account admission heartbeat failed for {self.account_id}: "
                f"{heartbeat_error}"
            ) from heartbeat_error
        if release_error is not None:
            raise QuotaAdmissionError(
                f"Account admission release failed for {self.account_id}: {release_error}"
            ) from release_error
        return False


def admission_lease_for_project(
    project_root: Path,
    *,
    account_id: str,
    run_id: str,
    lease_owner: str,
    home: Path | None = None,
    ttl_seconds: float = DEFAULT_ADMISSION_TTL_SECONDS,
    interval_seconds: float = DEFAULT_ADMISSION_HEARTBEAT_SECONDS,
) -> AccountAdmissionLease:
    root = project_root.resolve()
    config = load_project_config(root)
    store = AccountAdmissionStore(home)
    return AccountAdmissionLease(
        store,
        account_id=account_id,
        project_instance_id=project_instance_id(root),
        project_id=config.project.id,
        run_id=run_id,
        lease_owner=lease_owner,
        ttl_seconds=ttl_seconds,
        interval_seconds=interval_seconds,
    )
