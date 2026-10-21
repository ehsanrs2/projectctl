"""Bounded private SQLite custody tests; no real project state or privileged setup."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.p3i_synthetic_sqlite_custody_lab import (
    LabRefusal, commit, initialize, inspect,
)


def _folder(tmp_path):
    folder = tmp_path / 'isolated'
    folder.mkdir(mode=0o700)
    return folder


def test_single_durable_authority_replay_and_sequence(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    assert inspect(folder) == 0
    digest = commit(folder, 1)
    assert len(digest) == 64
    assert inspect(folder) == 1
    with pytest.raises(LabRefusal, match='REPLAY'):
        commit(folder, 1)
    with pytest.raises(LabRefusal, match='REPLAY'):
        commit(folder, 3)
    assert inspect(folder) == 1
    commit(folder, 2)
    assert inspect(folder) == 2


def test_missing_authority_never_rebootstraps_on_read(tmp_path):
    folder = _folder(tmp_path)
    with pytest.raises(LabRefusal, match='MISSING_AUTHORITY'):
        inspect(folder)
    initialize(folder)
    with pytest.raises(LabRefusal, match='INITIALIZE_REQUIRES_EMPTY'):
        initialize(folder)
    (folder / 'synthetic-custody.sqlite3').unlink()
    with pytest.raises(LabRefusal, match='MISSING_AUTHORITY'):
        inspect(folder)


def test_private_owner_permissions(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    os.chmod(folder, 0o755)
    with pytest.raises(LabRefusal, match='PRIVATE_DIRECTORY'):
        inspect(folder)
    os.chmod(folder, 0o700)
    db = folder / 'synthetic-custody.sqlite3'
    os.chmod(db, 0o644)
    with pytest.raises(LabRefusal, match='UNSAFE_DB_FILE'):
        inspect(folder)


def _fault(folder: Path, *, phase: str, seq: int):
    script = (
        'import sys; from pathlib import Path; '
        'from scripts.p3i_synthetic_sqlite_custody_lab import commit; '
        f'commit(Path(sys.argv[1]), {seq}, '
        f'crash_{phase}=True)'
    )
    result = subprocess.run(
        [sys.executable, '-c', script, str(folder)],
        capture_output=True, timeout=15,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr


def test_crash_before_sqlite_commit_rolled_back_in_fresh_process(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    _fault(folder, phase='before', seq=1)
    assert inspect(folder) == 0
    commit(folder, 1)
    assert inspect(folder) == 1


def test_crash_after_sqlite_commit_visible_without_ack(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    _fault(folder, phase='after', seq=1)
    assert inspect(folder) == 1
    with pytest.raises(LabRefusal, match='REPLAY'):
        commit(folder, 1)


def test_corrupt_history_refuses_forged_highwater(tmp_path):
    import sqlite3
    folder = _folder(tmp_path)
    initialize(folder)
    commit(folder, 1)
    with sqlite3.connect(folder / 'synthetic-custody.sqlite3') as db:
        db.execute('UPDATE state SET high_water=2 WHERE id=1')
    with pytest.raises(LabRefusal, match='SEQUENCE_HISTORY_DISAGREEMENT'):
        inspect(folder)


def test_competing_writer_processes_cannot_both_commit_one_sequence(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    script = '''
import sys
from pathlib import Path
from scripts.p3i_synthetic_sqlite_custody_lab import LabRefusal, commit
try:
    commit(Path(sys.argv[1]), 1)
except LabRefusal:
    raise SystemExit(3)
'''
    children = [
        subprocess.Popen(
            [sys.executable, '-c', script, str(folder)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(2)
    ]
    results = [child.communicate(timeout=15) for child in children]
    assert sorted(child.returncode for child in children) == [0, 3], results
    assert inspect(folder) == 1


def test_synthetic_input_rejects_non_int_and_overflow(tmp_path):
    folder = _folder(tmp_path)
    initialize(folder)
    for bad in (0, -1, True, 1_000_001, '1'):
        with pytest.raises(LabRefusal, match='SEQUENCE_INVALID'):
            commit(folder, bad)
    assert inspect(folder) == 0
