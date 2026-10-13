"""M6.0 B1: bounded source snapshots, NOT a trace exporter.

No call to ProjectCTL's connect_db, migrations, locks or mutable RunStore.
The private reader emits no assessments, runs no worker and never writes
authority files. WAL/SHM stability must be tested before wiring a public CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from projectctl.core.enums import RunStatus
from projectctl.schemas.run import RunManifest, RunManifestV1
from projectctl.schemas.trace import TraceEventSummary
from projectctl.storage.sqlite import APPLICATION_ID, PROJECT_STATE_DB_VERSION
from projectctl.trace.format import trace_event_category

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RUN_EVENTS = 512
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_FILE_BY_KIND = {
    "claim_transition_evidence": "claim-transition.json",
    "context_manifest": "context-manifest.json",
    "evidence_manifest": "evidence-manifest.json",
    "execution_input_manifest": "execution-input-manifest.json",
    "integration_manifest": "integration-manifest.json",
    "publication_manifest": "publication-manifest.json",
    "review_receipt": "review-receipt.json",
    "verification_manifest": "verification-manifest.json",
    "worker_result": "worker-result.json",
}
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class TraceSnapshotError(Exception):
    """Safe error code only; OS/SQLite exception details are not exported."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _assert_supported_platform() -> None:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise TraceSnapshotError("source_unreadable")


def _valid_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise TraceSnapshotError("unsafe_source_path")
    return run_id


def _read_fd(fd: int, *, limit: int) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise TraceSnapshotError("source_unreadable")
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    after = os.fstat(fd)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or len(data) > limit or len(data) != info.st_size:
        raise TraceSnapshotError("source_changed")
    return bytes(data)


@contextmanager
def _directory_chain(project_root: Path, *components: str) -> Iterator[int]:
    """Descriptor-anchored traversal; never follow a symlinked projectctl path."""
    _assert_supported_platform()
    descriptors = []
    try:
        fd = os.open(project_root, _DIRECTORY_FLAGS)
        descriptors.append(fd)
        for name in components:
            fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=fd)
            descriptors.append(fd)
        yield fd
    except (OSError, ValueError) as exc:
        raise TraceSnapshotError("unsafe_source_path") from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


@dataclass(frozen=True)
class TraceFileSnapshot:
    source_kind: str
    content_sha256: str
    raw_bytes: bytes = field(repr=False)


def read_run_artifact(
    project_root: Path, run_id: str, source_kind: str
) -> TraceFileSnapshot | None:
    """Read only one allowlisted run artifact; missing leaf is not an error."""
    _valid_run_id(run_id)
    if source_kind not in _FILE_BY_KIND:
        raise TraceSnapshotError("unsafe_source_path")
    _assert_supported_platform()
    try:
        with _directory_chain(project_root, ".projectctl", "runs", run_id) as dirfd:
            try:
                fd = os.open(_FILE_BY_KIND[source_kind], _FILE_FLAGS, dir_fd=dirfd)
            except FileNotFoundError:
                return None
            try:
                data = _read_fd(fd, limit=MAX_ARTIFACT_BYTES)
            finally:
                os.close(fd)
    except TraceSnapshotError:
        raise
    except OSError:
        raise TraceSnapshotError("source_unreadable") from None
    return TraceFileSnapshot(source_kind, hashlib.sha256(data).hexdigest(), data)


def _stable_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise TraceSnapshotError("unsafe_source_path")
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _db_sidecars(path: Path) -> tuple[tuple[int, int, int, int, int] | None, ...]:
    return tuple(_file_identity(Path(str(path) + suffix)) for suffix in ("-wal", "-shm"))


@dataclass(frozen=True)
class TraceDbSnapshot:
    run_id: str
    task_id: str = field(repr=False)
    observed_status: RunStatus = RunStatus.PLANNED
    run_record_sha256: str = ""
    run_manifest_sha256: str = ""
    run_manifest_version: int = 2
    event_stream_sha256: str = ""
    events: tuple[TraceEventSummary, ...] = ()


def read_run_db_snapshot(project_root: Path, run_id: str) -> TraceDbSnapshot:
    """Capture one existing SQLite run and event stream in one RO transaction.

    Existing WAL sidecars are fingerprinted before and after. An absent WAL
    companion is not manufactured intentionally; if the SQLite VFS creates or
    modifies one, this read is rejected and the platform must be investigated.
    No output/collector calls this primitive until its acceptance tests pass.
    """
    _valid_run_id(run_id)
    _assert_supported_platform()
    root = Path(project_root)
    db = root / ".projectctl" / "state.sqlite"
    try:
        with _directory_chain(root, ".projectctl") as parentfd:
            fd = os.open("state.sqlite", _FILE_FLAGS, dir_fd=parentfd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise TraceSnapshotError("unsafe_source_path")
                before = _file_identity(db)
                if before is None or before[:2] != (info.st_dev, info.st_ino):
                    raise TraceSnapshotError("source_changed")
                sidecars = _db_sidecars(db)
                # A WAL file without pre-existing shared memory may lead
                # SQLite to create one in the project authority directory.
                if sidecars[0] is not None and sidecars[1] is None:
                    raise TraceSnapshotError("source_unreadable")
                uri = "file:" + quote(str(db.absolute()), safe="/") + "?mode=ro"
                conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0.2)
                try:
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA query_only=ON")
                    conn.execute("BEGIN")
                    app_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
                    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                    if app_id != APPLICATION_ID or version != PROJECT_STATE_DB_VERSION:
                        raise TraceSnapshotError("invalid_content")

                    row = conn.execute(
                        "SELECT run_id, task_id, status, terminal_reason, "
                        "execution_plan_digest, base_commit, candidate_commit, "
                        "created_at, completed_at, manifest_json "
                        "FROM runs WHERE run_id=?", (run_id,)
                    ).fetchone()
                    if row is None:
                        raise TraceSnapshotError("missing_source")
                    record = dict(row)
                    manifest_raw = record.pop("manifest_json")
                    if not isinstance(manifest_raw, str) or len(manifest_raw.encode("utf-8")) > MAX_ARTIFACT_BYTES:
                        raise TraceSnapshotError("invalid_content")
                    payload = json.loads(manifest_raw)
                    if not isinstance(payload, dict):
                        raise TraceSnapshotError("invalid_content")
                    mv = payload.get("schema_version", 1)
                    if mv == 1:
                        manifest = RunManifestV1.model_validate(payload)
                    elif mv == 2:
                        manifest = RunManifest.model_validate(payload)
                    else:
                        raise TraceSnapshotError("unsupported_schema")
                    if manifest.run_id != run_id or manifest.task_id != record["task_id"]:
                        raise TraceSnapshotError("identity_mismatch")
                    observed_status = RunStatus(record["status"])
                    # A v1 manifest may have distinct historical enum values.
                    if manifest.status.value != observed_status.value:
                        raise TraceSnapshotError("inconsistent_snapshot")

                    rows = conn.execute(
                        "SELECT id, created_at, event_type FROM run_events "
                        "WHERE run_id=? ORDER BY id LIMIT ?",
                        (run_id, MAX_RUN_EVENTS + 1)
                    ).fetchall()
                    if len(rows) > MAX_RUN_EVENTS:
                        raise TraceSnapshotError("source_unreadable")
                    public_events = []
                    selected_events = []
                    for event in rows:
                        occurred_at = datetime.fromisoformat(event["created_at"])
                        public_events.append(TraceEventSummary(
                            sequence=event["id"], occurred_at=occurred_at,
                            category=trace_event_category(event["event_type"])
                        ))
                        # No event payload columns are selected or hashed.
                        selected_events.append([event["id"], event["created_at"], event["event_type"]])
                    result = TraceDbSnapshot(
                        run_id=run_id, task_id=record["task_id"],
                        observed_status=observed_status,
                        run_record_sha256=_stable_sha(record),
                        run_manifest_sha256=hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest(),
                        run_manifest_version=mv,
                        event_stream_sha256=_stable_sha(selected_events),
                        events=tuple(public_events),
                    )
                    conn.execute("ROLLBACK")  # End read-only BEGIN; no changes.
                finally:
                    conn.close()
                # This detects ordinary concurrent modification and VFS effects;
                # formal proof of no side effects still requires platform tests.
                if _file_identity(db) != before or _db_sidecars(db) != sidecars:
                    raise TraceSnapshotError("inconsistent_snapshot")
                return result
            finally:
                os.close(fd)
    except TraceSnapshotError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError):
        raise TraceSnapshotError("source_unreadable") from None
