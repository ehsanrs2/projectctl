from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import RunLeaseError, RunStoreError
from projectctl.schemas.run import RunManifest
from projectctl.schemas.run_store import RunEventRecord, RunRecord
from projectctl.storage.sqlite import (
    PROJECT_STATE_DB_VERSION,
    connect_db,
    inspect_db,
)


_ACTIVE = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class RunStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.db_path = self.project_root / ".projectctl" / "state.sqlite"
        _, version = inspect_db(self.db_path)
        if version != PROJECT_STATE_DB_VERSION:
            raise RunStoreError(
                f"Project state database is v{version}; v{PROJECT_STATE_DB_VERSION} is required. "
                "Run projectctl migrate."
            )

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            task_id=row["task_id"],
            status=RunStatus(row["status"]),
            terminal_reason=RunTerminalReason(row["terminal_reason"]) if row["terminal_reason"] else None,
            execution_plan_digest=row["execution_plan_digest"],
            base_commit=row["base_commit"],
            candidate_commit=row["candidate_commit"],
            branch_name=row["branch_name"],
            worktree_id=row["worktree_id"],
            worktree_path=row["worktree_path"],
            worker_provider=row["worker_provider"],
            worker_thread_id=row["worker_thread_id"],
            lease_owner=row["lease_owner"],
            lease_expires_at=_parse(row["lease_expires_at"]),
            heartbeat_at=_parse(row["heartbeat_at"]),
            created_at=_parse(row["created_at"]),
            started_at=_parse(row["started_at"]),
            completed_at=_parse(row["completed_at"]),
            checkpoint_at=_parse(row["checkpoint_at"]),
            checkpoint_ref=row["checkpoint_ref"],
        )

    def create(
        self,
        manifest: RunManifest,
        *,
        worktree_path: Path,
        lease_owner: str | None = None,
        lease_ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> RunRecord:
        now = now or datetime.now(timezone.utc)
        lease_expires = (
            now + timedelta(seconds=lease_ttl_seconds)
            if lease_owner is not None
            else None
        )
        payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        conn = connect_db(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, task_id, status, terminal_reason, execution_plan_digest,
                    base_commit, candidate_commit, branch_name, worktree_id, worktree_path,
                    worker_provider, worker_thread_id, lease_owner, lease_expires_at,
                    heartbeat_at, created_at, started_at, completed_at, checkpoint_at,
                    checkpoint_ref, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.task_id,
                    manifest.status.value,
                    manifest.terminal_reason.value if manifest.terminal_reason else None,
                    manifest.execution_plan_digest,
                    manifest.base_commit,
                    manifest.candidate_commit,
                    manifest.branch_name,
                    manifest.worktree_id,
                    str(worktree_path),
                    manifest.worker.provider,
                    manifest.worker_thread_id,
                    lease_owner,
                    _iso(lease_expires),
                    _iso(now) if lease_owner else None,
                    _iso(now),
                    _iso(manifest.started_at),
                    _iso(manifest.completed_at),
                    _iso(manifest.checkpoint_at),
                    manifest.checkpoint_ref,
                    payload,
                ),
            )
            conn.execute(
                "INSERT INTO run_events(run_id, created_at, event_type, payload_json) VALUES (?, ?, ?, ?)",
                (manifest.run_id, _iso(now), "run.created", "{}"),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise RunStoreError(
                f"Could not create run {manifest.run_id}; an active run may already exist "
                f"for task {manifest.task_id}: {exc}"
            ) from exc
        finally:
            conn.close()
        return self.get(manifest.run_id)

    def get(self, run_id: str) -> RunRecord:
        conn = connect_db(self.db_path)
        try:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RunStoreError(f"Unknown run: {run_id}")
        return self._row_to_record(row)

    def manifest(self, run_id: str) -> RunManifest:
        conn = connect_db(self.db_path)
        try:
            row = conn.execute("SELECT manifest_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RunStoreError(f"Unknown run: {run_id}")
        return RunManifest.model_validate(json.loads(row[0]))

    def list(self, *, limit: int = 100) -> list[RunRecord]:
        conn = connect_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_record(row) for row in rows]

    def transition(
        self,
        run_id: str,
        *,
        expected: set[RunStatus],
        status: RunStatus,
        terminal_reason: RunTerminalReason | None = None,
        candidate_commit: str | None = None,
        worker_thread_id: str | None = None,
        checkpoint_at: datetime | None = None,
        checkpoint_ref: str | None = None,
        now: datetime | None = None,
    ) -> RunRecord:
        now = now or datetime.now(timezone.utc)
        conn = connect_db(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise RunStoreError(f"Unknown run: {run_id}")
            current = RunStatus(row["status"])
            if current not in expected:
                raise RunStoreError(
                    f"Run {run_id} transition rejected: expected "
                    f"{sorted(x.value for x in expected)}, found {current.value}."
                )

            manifest = RunManifest.model_validate(json.loads(row["manifest_json"]))
            completed_at = manifest.completed_at
            started_at = manifest.started_at
            if status == RunStatus.RUNNING and started_at is None:
                started_at = now
            if status not in _ACTIVE:
                completed_at = now

            updated_data = manifest.model_dump(mode="python")
            updated_data.update(
                {
                    "status": status,
                    "terminal_reason": terminal_reason,
                    "candidate_commit": candidate_commit if candidate_commit is not None else manifest.candidate_commit,
                    "worker_thread_id": worker_thread_id if worker_thread_id is not None else manifest.worker_thread_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "checkpoint_at": checkpoint_at if checkpoint_at is not None else manifest.checkpoint_at,
                    "checkpoint_ref": checkpoint_ref if checkpoint_ref is not None else manifest.checkpoint_ref,
                }
            )
            updated = RunManifest.model_validate(updated_data)
            payload = json.dumps(updated.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            conn.execute(
                """
                UPDATE runs
                SET status=?, terminal_reason=?, candidate_commit=?, worker_thread_id=?,
                    started_at=?, completed_at=?, checkpoint_at=?, checkpoint_ref=?,
                    manifest_json=?
                WHERE run_id=?
                """,
                (
                    status.value,
                    terminal_reason.value if terminal_reason else None,
                    updated.candidate_commit,
                    updated.worker_thread_id,
                    _iso(updated.started_at),
                    _iso(updated.completed_at),
                    _iso(updated.checkpoint_at),
                    updated.checkpoint_ref,
                    payload,
                    run_id,
                ),
            )
            conn.execute(
                "INSERT INTO run_events(run_id, created_at, event_type, payload_json) VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    _iso(now),
                    "run.transition",
                    json.dumps(
                        {"from": current.value, "to": status.value, "terminal_reason": terminal_reason.value if terminal_reason else None},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get(run_id)

    def acquire_lease(
        self,
        run_id: str,
        *,
        owner: str,
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> RunRecord:
        now = now or datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        conn = connect_db(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT lease_owner, lease_expires_at FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise RunStoreError(f"Unknown run: {run_id}")
            current_owner = row["lease_owner"]
            current_expires = _parse(row["lease_expires_at"])
            if (
                current_owner
                and current_owner != owner
                and current_expires is not None
                and current_expires > now
            ):
                raise RunLeaseError(
                    f"Run {run_id} is leased by {current_owner} until {current_expires.isoformat()}."
                )
            conn.execute(
                """
                UPDATE runs
                SET lease_owner=?, lease_expires_at=?, heartbeat_at=?
                WHERE run_id=?
                """,
                (owner, _iso(expires), _iso(now), run_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get(run_id)

    def heartbeat(
        self,
        run_id: str,
        *,
        owner: str,
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> RunRecord:
        now = now or datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        conn = connect_db(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT lease_owner FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise RunStoreError(f"Unknown run: {run_id}")
            if row["lease_owner"] != owner:
                raise RunLeaseError(
                    f"Run {run_id} lease is not owned by {owner}."
                )
            conn.execute(
                "UPDATE runs SET lease_expires_at=?, heartbeat_at=? WHERE run_id=?",
                (_iso(expires), _iso(now), run_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get(run_id)

    def release_lease(self, run_id: str, *, owner: str) -> RunRecord:
        conn = connect_db(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT lease_owner FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise RunStoreError(f"Unknown run: {run_id}")
            if row["lease_owner"] not in (None, owner):
                raise RunLeaseError(
                    f"Run {run_id} lease is owned by {row['lease_owner']}, not {owner}."
                )
            conn.execute(
                "UPDATE runs SET lease_owner=NULL, lease_expires_at=NULL WHERE run_id=?",
                (run_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get(run_id)

    def events(self, run_id: str) -> list[RunEventRecord]:
        conn = connect_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT id, run_id, created_at, event_type, payload_json "
                "FROM run_events WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            RunEventRecord(
                id=row["id"],
                run_id=row["run_id"],
                created_at=_parse(row["created_at"]),
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]
