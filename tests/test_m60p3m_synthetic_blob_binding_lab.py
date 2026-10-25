"""Pure disposable P3m storage, process SIGKILL, and quarantine cases."""
from __future__ import annotations

import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
import stat
import tempfile

import pytest
from scripts.p3m_synthetic_blob_binding_lab import Refusal, initialize, inspect, publish


def newroot(tmp):
    root = Path(tmp) / 'p3m-root'
    root.mkdir(mode=0o700)
    initialize(root)
    return root


def sub_publish(path, num, mode):
    publish(Path(path), num, **{mode: True})


def crashed_publish(root, seq, phase):
    ctx = multiprocessing.get_context('spawn')
    p = ctx.Process(target=sub_publish, args=(str(root), seq, phase))
    p.start()
    p.join(6)
    assert p.exitcode == -signal.SIGKILL, p.exitcode


def test_roundtrip_bind_two_objects():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        assert inspect(root) == {'status': 'CONSISTENT', 'high_water': 0, 'count': 0}
        for seq in (1, 2):
            answer = publish(root, seq)
            expected = f'{{"sequence":{seq},"data":"SYNTHETIC"}}\n'.encode()
            assert answer == {'status': 'COMMITTED', 'sequence': seq,
                              'sha256': hashlib.sha256(expected).hexdigest()}
            assert (root / 'objects' / f'{seq:08d}.obj').read_bytes() == expected
            assert stat.S_IMODE((root / 'objects' / f'{seq:08d}.obj').stat().st_mode) == 0o400
            assert inspect(root)['high_water'] == seq


def test_non_monotonic_duplicate_refused_no_write():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        with pytest.raises(Refusal, match='NON_MONOTONIC'):
            publish(root, 2)
        publish(root, 1)
        with pytest.raises(Refusal, match='NON_MONOTONIC'):
            publish(root, 1)
        assert inspect(root)['high_water'] == 1


def test_commit_after_fs_object_but_before_ledger_is_quarantined():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        crashed_publish(root, 1, 'kill_after_object')
        assert (root / 'objects' / '00000001.obj').exists()
        with pytest.raises(Refusal, match='ORPHAN'):
            inspect(root)
        with pytest.raises(Refusal, match='ORPHAN'):
            publish(root, 1)
        assert (root / 'objects' / '00000001.obj').exists()


def test_commit_after_sqlite_before_ack_persists():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        crashed_publish(root, 1, 'kill_after_commit')
        assert inspect(root) == {'status': 'CONSISTENT', 'high_water': 1, 'count': 1}
        with pytest.raises(Refusal, match='NON_MONOTONIC'):
            publish(root, 1)


@pytest.mark.parametrize('change', ['alter_bytes', 'remove_object', 'symlink', 'mode', 'hardlink'])
def test_committed_object_tamper_refuses_readback(change):
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        publish(root, 1)
        obj = root / 'objects' / '00000001.obj'
        if change == 'alter_bytes':
            obj.chmod(0o600)
            obj.write_bytes(b'not-the-original')
            obj.chmod(0o400)
        elif change == 'remove_object':
            obj.unlink()
        elif change == 'symlink':
            obj.unlink()
            obj.symlink_to('/dev/null')
        elif change == 'mode':
            obj.chmod(0o600)
        elif change == 'hardlink':
            os.link(obj, root / 'alias')
        with pytest.raises((Refusal, FileNotFoundError)):
            inspect(root)


def test_stray_stage_requires_quarantine():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        (root / 'objects' / '.stage-00000001').write_bytes(b'incomplete')
        with pytest.raises(Refusal, match='ORPHAN'):
            inspect(root)
        with pytest.raises(Refusal, match='ORPHAN'):
            publish(root, 1)


def test_lock_symlink_refused_without_modifying_external():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        lock = root / '.owner.lock'
        lock.unlink()
        lock.symlink_to('/dev/null')
        with pytest.raises((Refusal, OSError)):
            inspect(root)


def test_unsafe_root_or_owner():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        root.chmod(0o711)
        with pytest.raises(Refusal, match='WRONG_MODE'):
            inspect(root)


def test_fault_flag_exclusivity():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        with pytest.raises(Refusal, match='FAULT_FLAGS'):
            publish(root, 1, kill_after_object=True, kill_after_commit=True)
        assert inspect(root)['high_water'] == 0


def test_unknown_root_entry_refuses():
    with tempfile.TemporaryDirectory() as temp:
        root = newroot(temp)
        (root / 'intruder.txt').write_text('foreign')
        with pytest.raises(Refusal, match='UNEXPECTED_ROOT_ENTRY'):
            inspect(root)
