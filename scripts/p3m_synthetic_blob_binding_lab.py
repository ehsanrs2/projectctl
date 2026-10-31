"""M6.0 P3m disposable synthetic blob/SQLite binding experiment.

An isolated Custodian-owned tree only. No real ProjectCTL input, IPC endpoint,
producer authentication, rollback resistance or power-cut durability claim.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import sys

ACK = 'SYNTHETIC_DISPOSABLE_LAB'
LIMIT = 16
NAME = re.compile(r'^[0-9]{8}\.obj$')


class Refusal(Exception):
    """No authorization to publish or certify an unverified store."""


def _require(condition: bool, why: str):
    if not condition:
        raise Refusal(why)


def _fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _entry(path: Path, kind: int, mode: int):
    entry = path.lstat()
    _require(stat.S_IFMT(entry.st_mode) == kind, 'WRONG_INODE_TYPE')
    _require(entry.st_uid == os.geteuid(), 'WRONG_OWNER')
    _require(stat.S_IMODE(entry.st_mode) == mode, 'WRONG_MODE')
    if kind == stat.S_IFREG:
        _require(entry.st_nlink == 1, 'WRONG_LINK_COUNT')
    return entry


def _root(root: Path):
    _entry(root, stat.S_IFDIR, 0o700)
    _entry(root / 'objects', stat.S_IFDIR, 0o700)
    _entry(root / '.owner.lock', stat.S_IFREG, 0o600)
    _entry(root / 'authority.sqlite3', stat.S_IFREG, 0o600)


def _payload(seq: int) -> bytes:
    _require(type(seq) is int and 1 <= seq <= LIMIT, 'SEQUENCE_REFUSED')
    return f'{{"sequence":{seq},"data":"SYNTHETIC"}}\n'.encode('ascii')


def _db(root: Path) -> sqlite3.Connection:
    # Path layout/owner checked separately, and private 0700 root excludes other UIDs.
    con = sqlite3.connect(f'file:{root / "authority.sqlite3"}?mode=rw', uri=True, timeout=0,
                          isolation_level=None)
    try:
        _require(con.execute('PRAGMA journal_mode').fetchone()[0] == 'delete',
                 'JOURNAL_MODE_REFUSED')
        con.execute('PRAGMA synchronous=FULL')
        con.execute('PRAGMA foreign_keys=ON')
        return con
    except BaseException:
        con.close()
        raise


@contextmanager
def _owner_lock(root: Path):
    _root(root)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root / '.owner.lock', flags)
    try:
        fd_stat = os.fstat(fd)
        named = _entry(root / '.owner.lock', stat.S_IFREG, 0o600)
        _require((fd_stat.st_dev, fd_stat.st_ino) == (named.st_dev, named.st_ino),
                 'LOCK_ALIAS_REFUSED')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal('CONCURRENT_OWNER_REFUSED') from exc
        yield
    finally:
        os.close(fd)  # NEVER unlink this lock inode


def initialize(root: Path):
    """Root must have been independently created as a Custodian-owned 0700 dir."""
    _entry(root, stat.S_IFDIR, 0o700)
    _require(not any(root.iterdir()), 'INIT_NOT_EMPTY')
    (root / 'objects').mkdir(mode=0o700)
    for name in ('.owner.lock', 'authority.sqlite3'):
        fd = os.open(root / name,
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    con = _db(root)
    try:
        con.executescript('''
            CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id = 1), high_water INTEGER NOT NULL);
            INSERT INTO state(id,high_water) VALUES (1,0);
            CREATE TABLE receipt(
              sequence INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              sha256 TEXT NOT NULL,
              size INTEGER NOT NULL
            );
        ''')
    finally:
        con.close()
    _fsync_dir(root / 'objects')
    _fsync_dir(root)
    return {'status': 'CONSISTENT', 'high_water': 0, 'count': 0}


def _read(root: Path):
    _root(root)
    con = _db(root)
    try:
        row = con.execute('SELECT high_water FROM state WHERE id = 1').fetchone()
        _require(row is not None and type(row[0]) is int, 'STATE_MISSING')
        hw = row[0]
        _require(0 <= hw <= LIMIT, 'HIGH_WATER_INVALID')
        rec = con.execute('SELECT sequence,name,sha256,size FROM receipt ORDER BY sequence').fetchall()
    finally:
        con.close()
    _require({p.name for p in root.iterdir()} ==
             {'objects', '.owner.lock', 'authority.sqlite3'},
             'UNEXPECTED_ROOT_ENTRY')
    _require(len(rec) == hw, 'HIGH_WATER_MISMATCH')
    objects = root / 'objects'
    # Refuse all unrecognized names, including interrupted staging artifacts.
    files = list(objects.iterdir())
    _require(len(files) == len(rec), 'ORPHAN_OR_MISSING_OBJECT')
    named = {p.name for p in files}
    _require(named == {f'{n:08d}.obj' for n in range(1, hw + 1)},
             'OBJECT_NAME_MISMATCH')
    for seq, name, sha, size in rec:
        _require(type(seq) is int and 1 <= seq <= hw and name == f'{seq:08d}.obj',
                 'RECEIPT_SEQUENCE_INVALID')
        expected = _payload(seq)
        _require(type(sha) is str and sha == hashlib.sha256(expected).hexdigest()
                 and type(size) is int and size == len(expected), 'RECEIPT_CONTENT_INVALID')
        file = objects / name
        stat_before = _entry(file, stat.S_IFREG, 0o400)
        # No symlink traversal, no writer access to the private containing folder.
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            _require((st.st_dev, st.st_ino) == (stat_before.st_dev, stat_before.st_ino),
                     'OBJECT_REPLACED')
            content = os.read(fd, len(expected) + 1)
            _require(content == expected, 'OBJECT_BYTES_INVALID')
        finally:
            os.close(fd)
    return {'status': 'CONSISTENT', 'high_water': hw, 'count': hw}


def inspect(root: Path):
    with _owner_lock(root):
        return _read(root)


def publish(root: Path, seq: int, *, kill_after_object=False, kill_after_commit=False):
    payload = _payload(seq)
    _require(not (kill_after_object and kill_after_commit), 'FAULT_FLAGS_REFUSED')
    with _owner_lock(root):
        before = _read(root)
        _require(seq == before['high_water'] + 1, 'NON_MONOTONIC_PUBLISH_REFUSED')
        objects = root / 'objects'
        # Deliberately fixed staging identity for a one-publisher finite lab.
        stage = objects / f'.stage-{seq:08d}'
        final = objects / f'{seq:08d}.obj'
        _require(not stage.exists() and not stage.is_symlink(), 'STAGE_EXISTS')
        _require(not final.exists() and not final.is_symlink(), 'OBJECT_EXISTS')
        fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(payload)
                stream.flush()
            os.fchmod(fd, 0o400)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(objects)
        # link() has no replacement semantics: EEXIST refuses, not overwrite.
        os.link(stage, final, follow_symlinks=False)
        _fsync_dir(objects)
        stage.unlink()
        _fsync_dir(objects)
        if kill_after_object:
            os.kill(os.getpid(), signal.SIGKILL)
        digest = hashlib.sha256(payload).hexdigest()
        con = _db(root)
        try:
            con.execute('BEGIN IMMEDIATE')
            existing = con.execute('SELECT high_water FROM state WHERE id=1').fetchone()
            _require(existing == (seq - 1,), 'CONCURRENT_SEQUENCE_REFUSED')
            con.execute('INSERT INTO receipt(sequence,name,sha256,size) VALUES(?,?,?,?)',
                        (seq, final.name, digest, len(payload)))
            updated = con.execute('UPDATE state SET high_water=? WHERE id=1 AND high_water=?',
                                  (seq, seq - 1)).rowcount
            _require(updated == 1, 'HIGH_WATER_CAS_REFUSED')
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
        if kill_after_commit:
            os.kill(os.getpid(), signal.SIGKILL)
        return {'status': 'COMMITTED', 'sequence': seq, 'sha256': digest}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('init', 'inspect', 'publish'))
    p.add_argument('--workdir', required=True, type=Path)
    p.add_argument('--sequence', type=int)
    p.add_argument('--kill-after-object', action='store_true')
    p.add_argument('--kill-after-commit', action='store_true')
    p.add_argument('--acknowledge', choices=[ACK], required=True)
    a = p.parse_args(argv)
    try:
        if os.geteuid() == 0 or os.getuid() != os.geteuid():
            raise Refusal('ROOT_OR_SETUID_REFUSED')
        if (a.workdir.parent != Path('/var/tmp') or
                not re.fullmatch(r'projectctl-p3m-[a-zA-Z0-9_-]{4,32}',
                                 a.workdir.name)):
            raise Refusal('UNAPPROVED_WORKDIR')
        if a.operation != 'publish' and (a.sequence is not None or
            a.kill_after_object or a.kill_after_commit):
            raise Refusal('UNEXPECTED_ARGS')
        if a.operation == 'publish' and a.sequence is None:
            raise Refusal('SEQUENCE_REQUIRED')
        if a.operation == 'init':
            answer = initialize(a.workdir)
        elif a.operation == 'publish':
            answer = publish(a.workdir, a.sequence,
                             kill_after_object=a.kill_after_object,
                             kill_after_commit=a.kill_after_commit)
        else:
            answer = inspect(a.workdir)
        print(json.dumps(answer, sort_keys=True, separators=(',', ':')))
        return 0
    except (Refusal, FileNotFoundError, FileExistsError, OSError, sqlite3.Error,
            ValueError) as exc:
        print(f'P3M_LAB_REFUSED:{type(exc).__name__}')
        return 2


if __name__ == '__main__':
    sys.exit(main())
