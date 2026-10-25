"""Linux process-isolated P3l SIGKILL/socket restart tests."""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import signal
import socket
import stat
import tempfile
import threading
import time

import pytest

from scripts.p3i_synthetic_sqlite_custody_lab import initialize, inspect
from scripts.p3k_synthetic_ack_recovery_lab import IntakeRefusal, OutcomeUnknown, request
from scripts.p3l_synthetic_sigkill_socket_recovery_lab import serve

pytestmark = pytest.mark.skipif(
    not hasattr(socket, 'SO_PEERCRED') or os.name != 'posix',
    reason='Requires Linux peer credentials and Unix process kill',
)


def setup(base):
    base = Path(base)
    ledger, sockdir = base / 'ledger', base / 'socket'
    ledger.mkdir(mode=0o700)
    sockdir.mkdir(mode=0o711)
    initialize(ledger)
    return ledger, sockdir


def await_socket(sockdir):
    path = sockdir / 'intake.sock'
    for _ in range(150):
        try:
            if stat.S_IMODE(path.stat().st_mode) == 0o666:
                return path
        except FileNotFoundError:
            pass
        time.sleep(.02)
    raise AssertionError('server socket did not start')


def process_server(ledger, sockdir, **kw):
    p = multiprocessing.get_context('spawn').Process(
        target=serve, args=(sockdir, ledger),
        kwargs={'allowed_uid': os.geteuid(), 'max_requests': 1, **kw})
    p.start()
    assert p.pid
    await_socket(sockdir)
    return p


def graceful_server(ledger, sockdir, n=1, *, allowed_uid=None, **kw):
    ready = threading.Event()
    errors = []

    def body():
        try:
            serve(sockdir, ledger,
                  allowed_uid=os.geteuid() if allowed_uid is None else allowed_uid,
                  max_requests=n, ready=ready, **kw)
        except Exception as exc:
            errors.append(exc)
            ready.set()

    t = threading.Thread(target=body)
    t.start()
    assert ready.wait(4)
    assert not errors, errors
    return t, errors


def done(t, errors):
    t.join(4)
    assert not t.is_alive()
    assert not errors, errors


def test_crash_before_commit_requires_explicit_recovery():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        p = process_server(ledger, sockdir, crash_before_sequence=1)
        with pytest.raises(OutcomeUnknown):
            request(sockdir / 'intake.sock', 'issue', 1)
        p.join(5)
        assert p.exitcode == -signal.SIGKILL
        assert inspect(ledger) == 0
        assert (sockdir / 'intake.sock').exists()
        with pytest.raises(IntakeRefusal, match='REQUIRES_OPT_IN'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)
        t, errors = graceful_server(ledger, sockdir, recover_stale=True)
        assert request(sockdir / 'intake.sock', 'lookup', 1) == {'status': 'ABSENT'}
        done(t, errors)
        assert inspect(ledger) == 0
        assert not (sockdir / 'intake.sock').exists()


def test_crash_after_commit_recovered_no_reissue():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        p = process_server(ledger, sockdir, crash_after_sequence=1)
        with pytest.raises(OutcomeUnknown):
            request(sockdir / 'intake.sock', 'issue', 1)
        p.join(5)
        assert p.exitcode == -signal.SIGKILL
        assert inspect(ledger) == 1
        t, errors = graceful_server(ledger, sockdir, recover_stale=True, n=2)
        first = request(sockdir / 'intake.sock', 'lookup', 1)
        assert first['status'] == 'COMMITTED'
        assert len(first['sha256']) == 64
        assert request(sockdir / 'intake.sock', 'issue', 1) == {'status': 'REFUSED'}
        done(t, errors)
        assert inspect(ledger) == 1


def test_idle_sigkill_stale_socket_and_reopen():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        p = process_server(ledger, sockdir)
        os.kill(p.pid, signal.SIGKILL)
        p.join(5)
        assert p.exitcode == -signal.SIGKILL
        t, errors = graceful_server(ledger, sockdir, recover_stale=True)
        assert request(sockdir / 'intake.sock', 'issue', 1)['status'] == 'COMMITTED'
        done(t, errors)
        assert inspect(ledger) == 1


def test_second_live_server_must_be_refused_even_with_recovery():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        t, errors = graceful_server(ledger, sockdir)
        with pytest.raises(IntakeRefusal, match='ACTIVE_OWNER'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1,
                  recover_stale=True)
        assert request(sockdir / 'intake.sock', 'lookup', 1) == {'status': 'ABSENT'}
        done(t, errors)


@pytest.mark.parametrize('kind', ['symlink', 'regular'])
def test_non_socket_path_never_removed(kind):
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        path = sockdir / 'intake.sock'
        if kind == 'symlink':
            path.symlink_to('/dev/null')
        else:
            path.write_text('keep')
        with pytest.raises(IntakeRefusal, match='UNSAFE_SOCKET'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1,
                  recover_stale=True)
        assert path.is_symlink() if kind == 'symlink' else path.read_text() == 'keep'


def test_lock_symlink_refused():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        (sockdir / '.custodian-owner.lock').symlink_to('/dev/null')
        with pytest.raises(OSError):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)
        assert not (sockdir / 'intake.sock').exists()


def test_unauthorized_peer_consumes_request_without_commit():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        t, errors = graceful_server(ledger, sockdir, n=1,
                                    allowed_uid=os.geteuid() + 1)
        assert request(sockdir / 'intake.sock', 'issue', 1) == {'status': 'REFUSED'}
        done(t, errors)
        assert inspect(ledger) == 0


def test_fault_rejects_multiple_connections():
    with tempfile.TemporaryDirectory() as tmp:
        ledger, sockdir = setup(tmp)
        with pytest.raises(IntakeRefusal, match='ONE_REQUEST'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(),
                  max_requests=2, crash_after_sequence=1)
        assert not (sockdir / 'intake.sock').exists()
