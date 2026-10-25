"""Synthetic Unix socket intake, stdlib-only tests on Linux."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading

import pytest

from scripts.p3i_synthetic_sqlite_custody_lab import initialize, inspect
from scripts.p3j_synthetic_unix_intake_lab import (
    IntakeRefusal, _parse_frame, request, serve,
)

pytestmark = pytest.mark.skipif(
    not hasattr(socket, 'SO_PEERCRED'), reason='Linux SO_PEERCRED required'
)


def dirs():
    return tempfile.TemporaryDirectory(prefix='p3j-unit-', dir='/tmp')


def setup(base):
    ledger = Path(base) / 'ledger'
    ledger.mkdir(mode=0o700)
    initialize(ledger)
    sockdir = Path(base) / 'sock'
    sockdir.mkdir(mode=0o711)
    return ledger, sockdir


def test_admitted_uid_commits_then_replay_rejected():
    with dirs() as tmp:
        ledger, sockdir = setup(tmp)
        ready = threading.Event()
        th = threading.Thread(target=serve, args=(sockdir, ledger), kwargs={
            'allowed_uid': os.geteuid(), 'max_requests': 2, 'ready': ready,
        })
        th.start()
        assert ready.wait(3)
        first = request(sockdir / 'intake.sock', 1)
        second = request(sockdir / 'intake.sock', 1)
        th.join(3)
        assert not th.is_alive()
        assert first['status'] == 'COMMITTED'
        assert len(first['sha256']) == 64
        assert second == {'status': 'REFUSED'}
        assert inspect(ledger) == 1
        assert not (sockdir / 'intake.sock').exists()


def test_unapproved_peer_denied_before_commit():
    with dirs() as tmp:
        ledger, sockdir = setup(tmp)
        ready = threading.Event()
        th = threading.Thread(target=serve, args=(sockdir, ledger), kwargs={
            'allowed_uid': os.geteuid() + 1, 'max_requests': 1, 'ready': ready,
        })
        th.start()
        assert ready.wait(3)
        assert request(sockdir / 'intake.sock', 1) == {'status': 'REFUSED'}
        th.join(3)
        assert inspect(ledger) == 0


@pytest.mark.parametrize('raw', [
    b'not json\n', b'{}\n', b'{"v":true,"op":"issue","sequence":1}\n',
    b'{"v":1,"op":"issue","sequence":1,"path":"/etc/passwd"}\n',
    b'{"v":1,"op":"issue","sequence":1.0}\n',
    b'{"v":1,"v":1,"op":"issue","sequence":1}\n',
    b'{"v":1,"op":"issue","sequence":-1}\n',
    b'{' + b'A' * 200 + b'}\n', b'{"v":1,"op":"issue","sequence":1}',
])
def test_invalid_frames_refused(raw):
    with pytest.raises(IntakeRefusal):
        _parse_frame(raw)


def test_socket_alias_is_not_overwritten():
    with dirs() as tmp:
        ledger, sockdir = setup(tmp)
        (sockdir / 'intake.sock').symlink_to('/dev/null')
        with pytest.raises(IntakeRefusal, match='ALREADY_EXISTS'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)
        assert inspect(ledger) == 0


def test_missing_authority_is_not_bootstrapped():
    with dirs() as tmp:
        ledger, sockdir = setup(tmp)
        (ledger / 'synthetic-custody.sqlite3').unlink()
        with pytest.raises(Exception, match='MISSING_AUTHORITY'):
            serve(sockdir, ledger, allowed_uid=os.geteuid(), max_requests=1)


def test_client_detects_fake_server_credentials():
    with dirs() as tmp:
        ledger, sockdir = setup(tmp)
        ready = threading.Event()
        th = threading.Thread(target=serve, args=(sockdir, ledger), kwargs={
            'allowed_uid': os.geteuid(), 'max_requests': 1, 'ready': ready,
        })
        th.start()
        assert ready.wait(3)
        with pytest.raises(IntakeRefusal, match='SERVER_UID'):
            request(sockdir / 'intake.sock', 1, expected_uid=os.geteuid() + 1)
        # A rejected client still counts as a connection to the bounded server.
        th.join(3)
        assert inspect(ledger) == 0
