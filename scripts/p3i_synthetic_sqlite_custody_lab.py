"""M6.0 P3i: independent-process synthetic SQLite custody/sequence experiment.

LAB ONLY: never handles source ProjectCTL data or authenticates an issuer.
The same SQLite transaction stores both the synthetic receipt and high-water.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import os
import signal
import sqlite3
import stat
from pathlib import Path

_DB = "synthetic-custody.sqlite3"
_SCHEMA = """
CREATE TABLE state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    high_water INTEGER NOT NULL CHECK (high_water >= 0)
);
CREATE TABLE receipts (
    sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
    sha256 TEXT NOT NULL UNIQUE,
    payload BLOB NOT NULL
);
INSERT INTO state (id, high_water) VALUES (1, 0);
"""


class LabRefusal(ValueError):
    """Unsafe, unexpected or conflicting laboratory state."""


def _check_root(folder: Path) -> None:
    entry = folder.lstat()
    if (not stat.S_ISDIR(entry.st_mode)
            or entry.st_uid != os.geteuid()
            or stat.S_IMODE(entry.st_mode) != 0o700):
        raise LabRefusal("P3I_PRIVATE_DIRECTORY_REQUIRED")


def _db_path(folder: Path, *, existing: bool) -> Path:
    _check_root(folder)
    db_path = folder / _DB
    if existing:
        try:
            entry = db_path.lstat()
        except FileNotFoundError as exc:
            raise LabRefusal("P3I_MISSING_AUTHORITY_REFUSE") from exc
        if (not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) != 0o600
                or entry.st_nlink != 1):
            raise LabRefusal("P3I_UNSAFE_DB_FILE_REFUSE")
    return db_path


def _connect(folder: Path) -> sqlite3.Connection:
    path = _db_path(folder, existing=True)
    # mode=rw must refuse a missing database; SQLite may recover a hot journal.
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5,
                         isolation_level=None)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(folder: Path) -> None:
    """Explicit fresh-only bootstrap; never recreate a missing ledger on read."""
    path = _db_path(folder, existing=False)
    if list(folder.iterdir()):
        raise LabRefusal("P3I_INITIALIZE_REQUIRES_EMPTY_PRIVATE_DIRECTORY")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    try:
        with closing(_connect(folder)) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.executescript(_SCHEMA)
        parent = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        # Preserve the unexpected state for explicit review; no retry bootstrap.
        raise


def _synthetic_bytes(sequence: int) -> bytes:
    if type(sequence) is not int or not (1 <= sequence <= 1_000_000):
        raise LabRefusal("P3I_SEQUENCE_INVALID")
    return (f'{{"sequence":{sequence},"data":"SYNTHETIC"}}\n').encode("ascii")


def _verify(db: sqlite3.Connection) -> int:
    state = db.execute("SELECT high_water FROM state WHERE id=1").fetchone()
    if state is None or type(state[0]) is not int or state[0] < 0:
        raise LabRefusal("P3I_STATE_CORRUPT_REFUSE")
    high_water = state[0]
    rows = db.execute("SELECT sequence, sha256, payload FROM receipts ORDER BY sequence")
    last = 0
    for seq, digest, payload in rows:
        if seq != last + 1 or payload != _synthetic_bytes(seq):
            raise LabRefusal("P3I_HISTORY_CORRUPT_REFUSE")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise LabRefusal("P3I_DIGEST_CORRUPT_REFUSE")
        last = seq
    if last != high_water:
        raise LabRefusal("P3I_SEQUENCE_HISTORY_DISAGREEMENT")
    return high_water


def inspect(folder: Path) -> int:
    """Read from the persisted authority, never from caller checkpoint."""
    with closing(_connect(folder)) as db:
        db.execute("BEGIN IMMEDIATE")  # hot-journal recovery and locked view
        try:
            high_water = _verify(db)
        finally:
            db.rollback()
        return high_water


def commit(folder: Path, sequence: int, *, crash_before: bool = False,
           crash_after: bool = False) -> str:
    """One SQLite transaction updates receipt and high-water; crash windows optional."""
    payload = _synthetic_bytes(sequence)
    digest = hashlib.sha256(payload).hexdigest()
    with closing(_connect(folder)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            high_water = _verify(db)
            if sequence != high_water + 1:
                raise LabRefusal("P3I_REPLAY_GAP_OR_STALE_REFUSED")
            db.execute("INSERT INTO receipts VALUES (?, ?, ?)",
                       (sequence, digest, payload))
            db.execute("UPDATE state SET high_water=? WHERE id=1", (sequence,))
            if crash_before:
                os.kill(os.getpid(), signal.SIGKILL)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    if crash_after:
        os.kill(os.getpid(), signal.SIGKILL)
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("initialize", "commit", "inspect", "kill-before-commit", "kill-after-commit"))
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--acknowledge", choices=("SYNTHETIC_DISPOSABLE_LAB",))
    args = parser.parse_args(argv)
    # Prevent accidental run against arbitrary repository, source or system path.
    path = args.workdir
    if (os.geteuid() == 0 or os.getuid() != os.geteuid()
            or path.parent != Path("/var/tmp")
            or not path.name.startswith("projectctl-p3i-")
            or args.acknowledge != "SYNTHETIC_DISPOSABLE_LAB"):
        print("P3I_LAB_REFUSED")
        return 2
    try:
        if args.operation == "initialize":
            if args.sequence is not None:
                raise LabRefusal("P3I_UNEXPECTED_SEQUENCE")
            initialize(path)
            print("P3I_LAB_INITIALIZED")
        elif args.operation == "inspect":
            if args.sequence is not None:
                raise LabRefusal("P3I_UNEXPECTED_SEQUENCE")
            print(f"P3I_HIGH_WATER={inspect(path)}")
        else:
            if args.sequence is None:
                raise LabRefusal("P3I_SEQUENCE_REQUIRED")
            digest = commit(
                path, args.sequence,
                crash_before=args.operation == "kill-before-commit",
                crash_after=args.operation == "kill-after-commit",
            )
            print(f"P3I_SYNTHETIC_COMMIT_SHA256={digest}")
    except (OSError, sqlite3.Error, LabRefusal) as exc:
        print(f"P3I_LAB_REFUSED: {type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
