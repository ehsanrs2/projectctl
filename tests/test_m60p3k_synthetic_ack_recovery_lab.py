"""P3k stdlib Socket/SQLite synthetic ACK-loss recovery tests."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import threading

import pytest

from scripts.p3i_synthetic_sqlite_custody_lab import (
    LabRefusal, commit, initialize, inspect,
)
from scripts.p3k_synthetic_ack_recovery_lab import (
    IntakeRefusal, OutcomeUnknown, _parse_frame, lookup, request, serve,
)

pytestmark = pytest.mark.skipif(
    not hasattr(socket, 'SO_PEERCRED'), reason='Linux SO_PEERCRED required'
)


def setup(base):
    ledger = Path(base) / 'ledger'
    ledger.mkdir(mode=0o700)
    initialize(ledger)
    sockdir = Path(base) / 'sock'
    sockdir.mkdir(mode=0o711)
    return ledger, sockdir


def run_server(ledger, sockdir, *, requests, drop_ack_sequence=None,
               uid=None):
    ready = threading.Event()
    errors = []

    def target():
        try:
            serve(sockdir, ledger, allowed_uid=os.geteuid() if uid is None else uid,
                  max_requests=requests, drop_ack_sequence=drop_ack_sequence,
                  ready=ready)
        except Exception as exc:
            errors.append(exc)
            ready.set()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert not errors, errors
    return thread, errors


def finished(thread, errors):
    thread.join(5)
    assert not thread.is_alive()
    assert not errors, errors


def test_lost_ack_committed_then_lookup_no_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        th, err = run_server(ledger, sockdir, requests=3, drop_ack_sequence=1)
        with pytest.raises(OutcomeUnknown, match='OUTCOME_UNKNOWN'):
            request(sockdir / 'intake.sock', 'issue', 1)
        assert inspect(ledger) == 1
        reply = request(sockdir / 'intake.sock', 'lookup', 1)
        assert reply['status'] == 'COMMITTED'
        assert len(reply['sha256']) == 64
        assert request(sockdir / 'intake.sock', 'issue', 1) == {'status': 'REFUSED'}
        finished(th, err)
        assert not (sockdir / 'intake.sock').exists()
        assert inspect(ledger) == 1


def test_absent_and_verified_history_after_restart():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        th, err = run_server(ledger, sockdir, requests=2)
        assert request(sockdir / 'intake.sock', 'lookup', 1) == {'status': 'ABSENT'}
        first = request(sockdir / 'intake.sock', 'issue', 1)
        assert first['status'] == 'COMMITTED'
        finished(th, err)
        th2, err2 = run_server(ledger, sockdir, requests=2)
        assert request(sockdir / 'intake.sock', 'lookup', 1) == first
        assert request(sockdir / 'intake.sock', 'lookup', 2) == {'status': 'ABSENT'}
        finished(th2, err2)
        assert inspect(ledger) == 1


def test_denied_peer_cannot_read_back():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        commit(ledger, 1)
        th, err = run_server(ledger, sockdir, requests=1, uid=os.geteuid() + 1)
        assert request(sockdir / 'intake.sock', 'lookup', 1) == {'status': 'REFUSED'}
        finished(th, err)
        assert inspect(ledger) == 1


def test_corrupt_ledger_refuses_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        commit(ledger, 1)
        # sqlite is intentionally writable only by the synthetic Custodian here
        import sqlite3
        db = sqlite3.connect(ledger / 'synthetic-custody.sqlite3')
        db.execute('UPDATE receipts SET sha256=? WHERE sequence=1', ('0' * 64,))
        db.commit()
        db.close()
        with pytest.raises(LabRefusal, match='DIGEST_CORRUPT'):
            lookup(ledger, 1)


def test_missing_ledger_refuses_start():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        (ledger / 'synthetic-custody.sqlite3').unlink()
        with pytest.raises(LabRefusal, match='MISSING_AUTHORITY'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)


def test_existing_socket_not_deleted_on_start():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        bogus = sockdir / 'intake.sock'
        bogus.symlink_to('/dev/null')
        with pytest.raises(IntakeRefusal, match='SOCKET_ALREADY_EXISTS'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)
        assert bogus.is_symlink()


@pytest.mark.parametrize('raw', [
    b'{}\n', b'{"v":1,"op":"query","sequence":1}\n',
    b'{"v":true,"op":"lookup","sequence":1}\n',
    b'{"v":1,"op":"lookup","sequence":false}\n',
    b'{"v":1,"op":"lookup","sequence":1,"path":"/etc"}\n',
    b'{"v":1,"v":1,"op":"issue","sequence":1}\n',
    b'{"v":1,"op":"lookup","sequence":1.0}\n',
    b'{"v":1,"op":"issue","sequence":0}\n',
    b'{"v":1,"op":"issue","sequence":1000001}\n',
    b'{"v":1,"op":"issue","sequence":1}',
    b'{' + b'x' * 200 + b'}\n',
])
def test_bad_frame_rejected(raw):
    with pytest.raises(IntakeRefusal):
        _parse_frame(raw)


def test_invalid_arguments_to_lookup_and_request():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        with pytest.raises(LabRefusal):
            lookup(ledger, 0)
        with pytest.raises(IntakeRefusal):
            request(sockdir / 'intake.sock', 'reset', 1)
        with pytest.raises(LabRefusal):
            request(sockdir / 'intake.sock', 'issue', True)


def test_fake_server_uid_refused_before_write():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        th, err = run_server(ledger, sockdir, requests=1)
        with pytest.raises(IntakeRefusal, match='SERVER_UID'):
            request(sockdir / 'intake.sock', 'lookup', 1,
                    expected_uid=os.geteuid() + 1)
        finished(th, err)
        assert inspect(ledger) == 0


def test_stale_unix_socket_refused_without_auto_unlink():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        path = sockdir / 'intake.sock'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as dead:
            dead.bind(str(path))
        assert path.exists()
        with pytest.raises(IntakeRefusal, match='SOCKET_ALREADY_EXISTS'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)
        assert path.exists()
        assert inspect(ledger) == 0
