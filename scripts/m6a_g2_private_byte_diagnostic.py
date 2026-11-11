"""M6a-G2: PRIVATE, untrusted byte-only, incomplete diagnostic prototype.

NO filesystem access, source reader, CLI, network, Worker or authority.
Caller-supplied bytes are untrusted; no evidence of source origin, same epoch,
capture safety, custody, current status, provider completion or safe retry.
This is research code under scripts/, NOT a production Trace interface.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime

from projectctl.core.enums import RunStatus
from projectctl.schemas.run import RunManifest, RunManifestV1
from projectctl.schemas.trace import TraceEventSummary
from projectctl.storage.sqlite import APPLICATION_ID, PROJECT_STATE_DB_VERSION
from projectctl.trace.format import canonical_trace_json_bytes, trace_event_category
from projectctl.trace.snapshot import (
    MAX_ARTIFACT_BYTES, MAX_RUN_EVENTS, TraceDbSnapshot,
    TraceFileSnapshot, _stable_sha,
)
from projectctl.trace.validate import (
    conservative_trace_from_snapshots, inspect_artifact_snapshot,
)

_MAGIC = b"SQLite format 3\x00"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_MAX_DB = 16 * 1024 * 1024
_KINDS = ("context_manifest", "verification_manifest", "evidence_manifest")
_DECISION = "M6A_OFFLINE_DIAGNOSTIC_INCOMPLETE_ONLY"


class G2Refused(ValueError):
    """Sanitized non-authorizing refusal without user paths or byte contents."""


@dataclass(frozen=True)
class G2Diagnostic:
    decision: str
    canonical_trace: bytes = field(repr=False)
    completeness: str
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    source_capture_nonmutation_proven: bool = False
    authenticated_custody_proven: bool = False
    current_state_proven: bool = False
    authorizes_export_cli: bool = False
    authorizes_retry: bool = False

    def __post_init__(self):
        if self.decision != _DECISION or self.completeness not in (
            "incomplete", "inconsistent"
        ) or any((
            self.source_origin_proven, self.cross_store_epoch_proven,
            self.source_capture_nonmutation_proven,
            self.authenticated_custody_proven, self.current_state_proven,
            self.authorizes_export_cli, self.authorizes_retry,
        )):
            raise ValueError("UNSAFE_DIAGNOSTIC_AUTHORITY")


def _valid_identifier(s: str) -> str:
    if type(s) is not str or not _ID.fullmatch(s):
        raise G2Refused("INVALID_IDENTITY")
    return s


def _no_duplicates(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError("DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def _decode_manifest(raw: str) -> dict:
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise G2Refused("INVALID_RUN_MANIFEST")
    try:
        obj = json.loads(
            raw, object_pairs_hook=_no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise G2Refused("INVALID_RUN_MANIFEST") from None
    if not isinstance(obj, dict):
        raise G2Refused("INVALID_RUN_MANIFEST")
    return obj


def _memory_snapshot(db_bytes: bytes, run_id: str) -> TraceDbSnapshot:
    if (type(db_bytes) is not bytes or not 512 <= len(db_bytes) <= _MAX_DB
            or not db_bytes.startswith(_MAGIC)):
        raise G2Refused("INVALID_SQLITE_BYTES")
    if db_bytes[18:20] != b"\x01\x01":
        raise G2Refused("UNSUPPORTED_WAL_INPUT")
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        if not hasattr(conn, "deserialize"):
            raise G2Refused("MEMORY_DESERIALIZE_UNAVAILABLE")
        if not hasattr(conn, "set_progress_handler"):
            raise G2Refused("MEMORY_STEP_GUARD_UNAVAILABLE")
        # Bound query VM instructions even on an adversarial SQLite byte image.
        # This is a lab ceiling, not an OS-level hard CPU/memory sandbox:
        # deserialization and Python model validation are still separate.
        progress = [0]

        def limited_progress() -> int:
            progress[0] += 1
            return int(progress[0] > 1000)

        conn.set_progress_handler(limited_progress, 1000)
        try:
            # Reject unsafe schema functions before any supplied schema is used.
            conn.execute("PRAGMA trusted_schema=OFF")
            if hasattr(conn, "setlimit"):
                conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_ARTIFACT_BYTES + 262144)
                conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
            conn.deserialize(db_bytes)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            if (conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                    or conn.execute("PRAGMA user_version").fetchone()[0]
                    != PROJECT_STATE_DB_VERSION):
                raise G2Refused("UNSUPPORTED_SOURCE_VERSION")
            # A SQLite view or virtual table named "runs" may execute
            # attacker-controlled SQL or extensions on otherwise fixed SELECT.
            # Permit ONLY ordinary tables at the two queried names.
            objects = conn.execute(
                "SELECT name, type, sql FROM sqlite_schema "
                "WHERE name IN ('runs', 'run_events')"
            ).fetchall()
            if (len(objects) != 2
                    or {item["name"] for item in objects} != {"runs", "run_events"}
                    or any(item["type"] != "table"
                           or type(item["sql"]) is not str
                           or re.match(r"^\s*CREATE\s+TABLE\b",
                                       item["sql"], re.IGNORECASE) is None
                           for item in objects)):
                raise G2Refused("UNSAFE_SQLITE_SCHEMA_OBJECT")
            row = conn.execute(
                "SELECT run_id, task_id, status, terminal_reason, "
                "execution_plan_digest, base_commit, candidate_commit, "
                "created_at, completed_at, manifest_json "
                "FROM runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if row is None:
                raise G2Refused("MISSING_RUN")
            record = dict(row)
            raw_manifest = record.pop("manifest_json")
            manifest = _decode_manifest(raw_manifest)
            version = manifest.get("schema_version", 1)
            if type(version) is not int or version not in (1, 2):
                raise G2Refused("UNSUPPORTED_RUN_SCHEMA")
            parsed = (RunManifestV1 if version == 1 else RunManifest).model_validate(manifest)
            status = RunStatus(record["status"])
            if (record["run_id"] != run_id or type(record["task_id"]) is not str
                    or parsed.run_id != run_id or manifest.get("run_id") != run_id
                    or parsed.task_id != record["task_id"]
                    or manifest.get("task_id") != record["task_id"]
                    or parsed.status.value != status.value):
                raise G2Refused("INCONSISTENT_RUN_RECORD")
            events = conn.execute(
                "SELECT id, created_at, event_type FROM run_events "
                "WHERE run_id=? ORDER BY id LIMIT ?",
                (run_id, MAX_RUN_EVENTS + 1),
            ).fetchall()
            if len(events) > MAX_RUN_EVENTS:
                raise G2Refused("UNBOUNDED_EVENT_STREAM")
            summaries = []
            selected = []
            for ev in events:
                occurred = datetime.fromisoformat(ev["created_at"])
                summaries.append(TraceEventSummary(
                    sequence=ev["id"], occurred_at=occurred,
                    category=trace_event_category(ev["event_type"]),
                ))
                selected.append([ev["id"], ev["created_at"], ev["event_type"]])
            return TraceDbSnapshot(
                run_id=run_id,
                task_id=record["task_id"],
                observed_status=status,
                run_record_sha256=_stable_sha(record),
                run_manifest_sha256=hashlib.sha256(raw_manifest.encode("utf-8")).hexdigest(),
                run_manifest_version=version,
                event_stream_sha256=_stable_sha(selected),
                events=tuple(summaries),
            )
        except G2Refused:
            raise
        except (sqlite3.Error, ValueError, TypeError, OverflowError,
                UnicodeError, RecursionError):
            raise G2Refused("INVALID_OR_UNSUPPORTED_INPUT") from None


def inspect_untrusted_supplied_bytes(
    *, db_bytes: bytes, run_id: str, project_id: str,
    artifact_bytes: dict[str, bytes | None],
) -> G2Diagnostic:
    """Return only deterministic redacted incomplete trace from untrusted bytes.

    The API has NO filesystem path parameter and does not accept an inventory
    as origin evidence. It is private research and must never dispatch work.
    """
    _valid_identifier(run_id)
    _valid_identifier(project_id)
    if type(artifact_bytes) is not dict or set(artifact_bytes) != set(_KINDS):
        raise G2Refused("INVALID_ARTIFACT_SET")
    for kind, raw in artifact_bytes.items():
        if raw is not None and (type(raw) is not bytes or len(raw) > MAX_ARTIFACT_BYTES):
            raise G2Refused("INVALID_ARTIFACT_BYTES")
    snapshot = _memory_snapshot(db_bytes, run_id)
    descriptors = {
        kind: inspect_artifact_snapshot(
            None if artifact_bytes[kind] is None else TraceFileSnapshot(
                kind,
                hashlib.sha256(artifact_bytes[kind]).hexdigest(),
                artifact_bytes[kind],
            ),
            source_kind=kind, run_id=run_id,
            task_id=snapshot.task_id, project_id=project_id,
        )
        for kind in _KINDS
    }
    bundle = conservative_trace_from_snapshots(
        project_id=project_id, db_snapshot=snapshot, file_sources=descriptors,
    )
    if bundle.completeness not in ("incomplete", "inconsistent") or bundle.assessments:
        raise G2Refused("UNSAFE_TRACE_RESULT")
    return G2Diagnostic(_DECISION, canonical_trace_json_bytes(bundle), bundle.completeness)
