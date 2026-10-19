"""M6.0 B-Diagnostic detached input verifier — EXPERIMENT ONLY.

Consumes an explicitly labelled, synthetic, self-contained fixture. It
does NOT create snapshots, certify their source, freeze concurrent writers,
verify a trusted signature, implement R1, or expose a public Trace CLI.

Do not pass a real ProjectCTL project to this verifier. There is no CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from projectctl.trace.format import canonical_trace_json_bytes
from projectctl.trace.snapshot import (
    TraceSnapshotError, read_run_artifact, read_run_db_snapshot,
)
from projectctl.trace.validate import (
    conservative_trace_from_snapshots, inspect_artifact_snapshot,
)

PREFIX = "projectctl-bdiag-detached-"
RUN = "run-bdiag-detached"
TASK = "task-bdiag-detached"
PROJECT = "bdiag-detached-test"
DB = ".projectctl/state.sqlite"
CONTEXT = ".projectctl/runs/" + RUN + "/context-manifest.json"
INVENTORY = "bdiag-inventory.json"
PATHS = (DB, CONTEXT)
LIMITS = {DB: 16 * 1024 * 1024, CONTEXT: 2 * 1024 * 1024,
          INVENTORY: 8192}
# Static checked-in schema: no source-authority or integrity-signing secret.
FORMAT = "m6.0-bdiag-detached-fixture-v1"


class DetachedRefusal(ValueError):
    """Safe, constant diagnostic code; never print file contents or paths."""


@dataclass(frozen=True)
class DetachedObservation:
    decision: str
    canonical_trace: bytes
    completeness: str
    sampled_file_identity_unchanged: bool = True
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    independently_immutable_proven: bool = False
    authorizes_collector_or_cli: bool = False
    authorizes_live_wal_reader: bool = False
    authorizes_writer_seal: bool = False
    authorizes_migration: bool = False

    def __post_init__(self):
        if self.decision != "NO_GO_DETACHED_FIXTURE_BYTES_ONLY":
            raise ValueError("non_authorizing_decision_required")
        if not all((
            self.source_origin_proven is False,
            self.cross_store_epoch_proven is False,
            self.independently_immutable_proven is False,
            self.authorizes_collector_or_cli is False,
            self.authorizes_live_wal_reader is False,
            self.authorizes_writer_seal is False,
            self.authorizes_migration is False,
        )):
            raise ValueError("unsafe_authority_claim")


def _nonroot_posix() -> None:
    if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "pread")
            or os.geteuid() == 0 or os.getuid() == 0):
        raise DetachedRefusal("UNSUPPORTED_NONROOT_PLATFORM")


def _directory(path: Path) -> tuple[int, ...]:
    try:
        info = path.lstat()
    except OSError:
        raise DetachedRefusal("UNAVAILABLE_PRIVATE_DIRECTORY") from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise DetachedRefusal("UNTRUSTED_PRIVATE_DIRECTORY")
    return (info.st_dev, info.st_ino, info.st_mode,
            info.st_mtime_ns, info.st_ctime_ns)


def _exact_leaves(directory: Path, expected: set[str]) -> None:
    try:
        names = {name for name in os.listdir(directory)}
    except OSError:
        raise DetachedRefusal("UNAVAILABLE_PRIVATE_DIRECTORY") from None
    if names != expected:
        raise DetachedRefusal("UNEXPECTED_OR_MISSING_PRIVATE_ENTRY")


def _read_owned(path: Path, max_bytes: int) -> tuple[bytes, tuple[int, ...]]:
    try:
        original = path.lstat()
    except OSError:
        raise DetachedRefusal("MISSING_PRIVATE_LEAF") from None
    if (not stat.S_ISREG(original.st_mode) or original.st_uid != os.getuid()
            or original.st_nlink != 1
            or stat.S_IMODE(original.st_mode) != 0o400
            or original.st_size > max_bytes):
        raise DetachedRefusal("UNTRUSTED_PRIVATE_LEAF")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (
                original.st_dev, original.st_ino
            ):
                raise DetachedRefusal("PRIVATE_LEAF_RACE")
            chunks = bytearray()
            while len(chunks) <= max_bytes:
                part = os.read(fd, min(65536, max_bytes + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
            final = os.fstat(fd)
        finally:
            os.close(fd)
        live = path.lstat()
    except DetachedRefusal:
        raise
    except OSError:
        raise DetachedRefusal("PRIVATE_LEAF_READ_REFUSED") from None
    def identity(item):
        return (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if (identity(original) != identity(opened)
            or identity(original) != identity(final)
            or identity(original) != identity(live)
            or len(chunks) != original.st_size or len(chunks) > max_bytes):
        raise DetachedRefusal("PRIVATE_LEAF_CHANGED")
    return bytes(chunks), identity(original)


def _inventory_payload(file_bytes: dict[str, bytes]) -> dict[str, object]:
    """Computed integrity claims, NOT signed origin or a cross-store epoch."""
    return {
        "format": FORMAT,
        "test_fixture_only": True,
        "source_origin": "UNATTESTED",
        "cross_store_epoch": "UNATTESTED",
        "external_producer_signature": "ABSENT",
        "files": [
            {"path": name, "sha256": hashlib.sha256(file_bytes[name]).hexdigest(),
             "size": len(file_bytes[name])}
            for name in sorted(PATHS)
        ],
    }


def canonical_inventory(file_bytes: dict[str, bytes]) -> bytes:
    if set(file_bytes) != set(PATHS):
        raise ValueError("exact_fixture_file_set_required")
    return (json.dumps(_inventory_payload(file_bytes), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _observe(root: Path):
    _nonroot_posix()
    if (not root.is_absolute() or root.name in {".", ".."}
            or not root.name.startswith(PREFIX)
            or root.parent.is_symlink()):
        raise DetachedRefusal("OUTSIDE_TEST_FIXTURE_SCOPE")
    top = _directory(root)
    internal = _directory(root / ".projectctl")
    runs = _directory(root / ".projectctl/runs")
    selected = _directory(root / ".projectctl/runs" / RUN)
    _exact_leaves(root, {"bdiag-inventory.json", ".projectctl"})
    _exact_leaves(root / ".projectctl", {"state.sqlite", "runs"})
    _exact_leaves(root / ".projectctl/runs", {RUN})
    _exact_leaves(root / ".projectctl/runs" / RUN, {"context-manifest.json"})
    # No WAL, SHM, hot rollback journal, backup or unexpected aliases may exist.
    snapshots = {
        name: _read_owned(root / name, LIMITS[name]) for name in PATHS
    }
    inventory, inventory_identity = _read_owned(
        root / INVENTORY, LIMITS[INVENTORY]
    )
    file_bytes = {name: snapshots[name][0] for name in PATHS}
    if inventory != canonical_inventory(file_bytes):
        raise DetachedRefusal("INVENTORY_INTEGRITY_OR_AUTHORITY_MISMATCH")
    return (
        (top, internal, runs, selected),
        {name: (hashlib.sha256(raw).hexdigest(), ident)
         for name, (raw, ident) in snapshots.items()},
        (hashlib.sha256(inventory).hexdigest(), inventory_identity),
    )


def inspect_detached_test_fixture(root: Path) -> DetachedObservation:
    """Read the detached fixture only; never read or name an origin project.

    Even all matched hashes are SELF-ASSERTED. No one proves who produced
    them, whether a writer was active, or one DB+JSON source instant.
    """
    root = Path(root)
    before = _observe(root)
    try:
        db = read_run_db_snapshot(root, RUN)
        if db.task_id != TASK:
            raise DetachedRefusal("DETACHED_IDENTITY_MISMATCH")
        context = read_run_artifact(root, RUN, "context_manifest")
        descriptor = inspect_artifact_snapshot(
            context, source_kind="context_manifest",
            run_id=RUN, task_id=TASK, project_id=PROJECT,
        )
        missing_verification = inspect_artifact_snapshot(
            None, source_kind="verification_manifest",
            run_id=RUN, task_id=TASK, project_id=PROJECT,
        )
        missing_evidence = inspect_artifact_snapshot(
            None, source_kind="evidence_manifest",
            run_id=RUN, task_id=TASK, project_id=PROJECT,
        )
        trace = conservative_trace_from_snapshots(
            project_id=PROJECT, db_snapshot=db,
            file_sources={
                "context_manifest": descriptor,
                "verification_manifest": missing_verification,
                "evidence_manifest": missing_evidence,
            },
        )
        encoded = canonical_trace_json_bytes(trace)
    except DetachedRefusal:
        raise
    except (TraceSnapshotError, OSError, ValueError, TypeError):
        raise DetachedRefusal("DETACHED_TRACE_READ_REFUSED") from None
    if before != _observe(root):
        raise DetachedRefusal("DETACHED_FIXTURE_CHANGED")
    if trace.completeness not in ("incomplete", "inconsistent") or trace.assessments:
        raise DetachedRefusal("UNSAFE_TRACE_ASSERTION")
    return DetachedObservation(
        decision="NO_GO_DETACHED_FIXTURE_BYTES_ONLY",
        canonical_trace=encoded,
        completeness=trace.completeness,
    )
