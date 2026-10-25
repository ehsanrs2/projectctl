"""M6.0 P3k: synthetic ACK-loss reconciliation over a bounded Unix socket.

Disposable Linux lab only. A lookup reads the P3i SQLite authority, not a
Writer-owned checkpoint. It does not prove source provenance or rollback safety.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import pwd
import re
import socket
import sqlite3
import stat
import sys
from typing import Any

if __package__:
    from scripts.p3i_synthetic_sqlite_custody_lab import (
        LabRefusal, _connect, _synthetic_bytes, _verify, commit, inspect,
    )
    from scripts.p3j_synthetic_unix_intake_lab import (
        IntakeRefusal, _lab_path, _peer_uid, _private_socket_dir,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from p3i_synthetic_sqlite_custody_lab import (
        LabRefusal, _connect, _synthetic_bytes, _verify, commit, inspect,
    )
    from p3j_synthetic_unix_intake_lab import (
        IntakeRefusal, _lab_path, _peer_uid, _private_socket_dir,
    )

_SOCK_NAME = 'intake.sock'
_MAX_BYTES = 128
_ACK = 'SYNTHETIC_DISPOSABLE_LAB'


class OutcomeUnknown(IntakeRefusal):
    """Transport lost an issue ACK; do not reissue without reconciliation."""


def _parse_frame(raw: bytes) -> tuple[str, int]:
    if not 2 <= len(raw) <= _MAX_BYTES or not raw.endswith(b'\n'):
        raise IntakeRefusal('P3K_FRAME_REFUSED')

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IntakeRefusal('P3K_DUPLICATE_JSON_KEY_REFUSED')
            result[key] = value
        return result

    try:
        obj: Any = json.loads(raw[:-1].decode('ascii'),
                              object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError) as exc:
        raise IntakeRefusal('P3K_JSON_REFUSED') from exc
    if (type(obj) is not dict or set(obj) != {'v', 'op', 'sequence'}
            or type(obj['v']) is not int or obj['v'] != 1
            or type(obj['op']) is not str or obj['op'] not in ('issue', 'lookup')
            or type(obj['sequence']) is not int
            or not (1 <= obj['sequence'] <= 1_000_000)):
        raise IntakeRefusal('P3K_SCHEMA_REFUSED')
    return obj['op'], obj['sequence']


def lookup(ledger_dir: Path, sequence: int) -> dict:
    """Verify one consistent committed ledger snapshot; never create a DB."""
    _synthetic_bytes(sequence)  # shared strict range/type check
    with closing(_connect(ledger_dir)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            high_water = _verify(db)  # verifies all receipts, not just a row
            if sequence > high_water:
                return {'status': 'ABSENT'}
            row = db.execute('SELECT sha256 FROM receipts WHERE sequence=?',
                             (sequence,)).fetchone()
            if row is None:
                raise LabRefusal('P3K_VERIFIED_RECEIPT_MISSING_REFUSE')
            return {'status': 'COMMITTED', 'sha256': row[0]}
        finally:
            db.rollback()


def _send(conn: socket.socket, result: dict) -> None:
    try:
        conn.sendall(json.dumps(result, sort_keys=True,
                                separators=(',', ':')).encode('ascii') + b'\n')
    except (OSError, socket.timeout):
        # An ACK failing *after* SQLite commit never reverses the transaction.
        pass


def serve(socket_dir: Path, ledger_dir: Path, *, allowed_uid: int,
          max_requests: int, drop_ack_sequence: int | None = None,
          ready=None) -> None:
    """Serve at most 16 connections in foreground; clean socket on normal exit.

    drop_ack_sequence is an explicit lab-only fault, affecting *issue* only.
    No automatic stale-socket removal after abnormal process termination.
    """
    if (not hasattr(socket, 'SO_PEERCRED')
            or not (0 <= allowed_uid < 2**32 and 1 <= max_requests <= 16)
            or (drop_ack_sequence is not None
                and (type(drop_ack_sequence) is not int
                     or not 1 <= drop_ack_sequence <= 1_000_000))):
        raise IntakeRefusal('P3K_LAUNCH_LIMITS_REFUSED')
    _private_socket_dir(socket_dir)
    inspect(ledger_dir)  # fail closed if existing authority is unsafe
    path = socket_dir / _SOCK_NAME
    if path.exists() or path.is_symlink():
        raise IntakeRefusal('P3K_SOCKET_ALREADY_EXISTS')
    if len(os.fsencode(path)) >= 105:
        raise IntakeRefusal('P3K_SOCKET_PATH_TOO_LONG')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        identity = path.lstat()
        try:
            os.chmod(path, 0o666)
            listener.listen(4)
            if ready is not None:
                ready.set()
            for _ in range(max_requests):
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(2)
                    try:
                        if _peer_uid(conn) != allowed_uid:
                            raise IntakeRefusal('P3K_PEER_UID_REFUSED')
                        frame = bytearray()
                        while len(frame) <= _MAX_BYTES:
                            block = conn.recv(_MAX_BYTES + 1 - len(frame))
                            if not block:
                                break
                            frame.extend(block)
                        operation, sequence = _parse_frame(bytes(frame))
                        if operation == 'lookup':
                            result = lookup(ledger_dir, sequence)
                        else:
                            digest = commit(ledger_dir, sequence)
                            result = {'status': 'COMMITTED', 'sha256': digest}
                    except (IntakeRefusal, LabRefusal, sqlite3.Error,
                            OSError, ValueError, socket.timeout):
                        _send(conn, {'status': 'REFUSED'})
                    else:
                        if operation == 'issue' and sequence == drop_ack_sequence:
                            # Deliberately suppress ACK after a committed transaction.
                            continue
                        _send(conn, result)
        finally:
            try:
                current = path.lstat()
                if (stat.S_ISSOCK(current.st_mode)
                        and (current.st_dev, current.st_ino)
                        == (identity.st_dev, identity.st_ino)):
                    path.unlink()
            except FileNotFoundError:
                pass


def request(path: Path, operation: str, sequence: int,
            *, expected_uid: int | None = None) -> dict:
    if operation not in ('issue', 'lookup'):
        raise IntakeRefusal('P3K_CLIENT_OPERATION_REFUSED')
    _synthetic_bytes(sequence)
    frame = json.dumps({'v': 1, 'op': operation, 'sequence': sequence},
                       separators=(',', ':')).encode('ascii') + b'\n'
    if len(frame) > _MAX_BYTES:
        raise IntakeRefusal('P3K_CLIENT_FRAME_TOO_LARGE')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(3)
            conn.connect(str(path))
            if expected_uid is not None and _peer_uid(conn) != expected_uid:
                raise IntakeRefusal('P3K_SERVER_UID_REFUSED')
            conn.sendall(frame)
            conn.shutdown(socket.SHUT_WR)
            response = conn.recv(256)
    except (OSError, socket.timeout) as exc:
        if operation == 'issue':
            raise OutcomeUnknown('P3K_ISSUE_OUTCOME_UNKNOWN') from exc
        raise IntakeRefusal('P3K_LOOKUP_UNAVAILABLE') from exc
    if not response or not response.endswith(b'\n') or len(response) > 256:
        if operation == 'issue':
            raise OutcomeUnknown('P3K_ISSUE_OUTCOME_UNKNOWN')
        raise IntakeRefusal('P3K_LOOKUP_RESPONSE_INVALID')
    try:
        parsed = json.loads(response.decode('ascii'))
    except (UnicodeDecodeError, ValueError) as exc:
        if operation == 'issue':
            raise OutcomeUnknown('P3K_ISSUE_OUTCOME_UNKNOWN') from exc
        raise IntakeRefusal('P3K_LOOKUP_RESPONSE_INVALID') from exc
    try:
        if type(parsed) is not dict or type(parsed.get('status')) is not str:
            raise IntakeRefusal('P3K_RESPONSE_SCHEMA_REFUSED')
        if parsed['status'] == 'COMMITTED':
            if (set(parsed) != {'status', 'sha256'}
                    or type(parsed['sha256']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', parsed['sha256']) is None):
                raise IntakeRefusal('P3K_RESPONSE_DIGEST_REFUSED')
        elif (parsed['status'] == 'REFUSED'
              or (operation == 'lookup' and parsed['status'] == 'ABSENT')):
            if set(parsed) != {'status'}:
                raise IntakeRefusal('P3K_RESPONSE_FIELDS_REFUSED')
        else:
            raise IntakeRefusal('P3K_RESPONSE_STATUS_REFUSED')
    except (IntakeRefusal, TypeError, KeyError) as exc:
        if operation == 'issue':
            raise OutcomeUnknown('P3K_ISSUE_OUTCOME_UNKNOWN') from exc
        raise IntakeRefusal('P3K_LOOKUP_RESPONSE_INVALID') from exc
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('serve', 'issue', 'lookup'))
    parser.add_argument('--socket-dir', required=True, type=Path)
    parser.add_argument('--ledger-dir', type=Path)
    parser.add_argument('--allow-uid', type=int)
    parser.add_argument('--max-requests', type=int)
    parser.add_argument('--drop-ack-sequence', type=int)
    parser.add_argument('--sequence', type=int)
    parser.add_argument('--acknowledge', choices=(_ACK,))
    args = parser.parse_args(argv)
    try:
        custodian_uid = pwd.getpwnam('p3-custodian').pw_uid
    except KeyError:
        print('P3K_LAB_REFUSED')
        return 2
    if (os.geteuid() == 0 or os.getuid() != os.geteuid()
            or args.acknowledge != _ACK
            or not _lab_path(args.socket_dir, 'projectctl-p3k-',
                             0o711, custodian_uid)):
        print('P3K_LAB_REFUSED')
        return 2
    try:
        if args.operation == 'serve':
            if (os.geteuid() != custodian_uid or args.allow_uid is None
                    or args.allow_uid == custodian_uid
                    or args.ledger_dir is None or args.max_requests is None
                    or args.sequence is not None
                    or not _lab_path(args.ledger_dir, 'projectctl-p3i-',
                                     0o700, custodian_uid)):
                raise IntakeRefusal('P3K_SERVER_ARGS_REFUSED')
            serve(args.socket_dir, args.ledger_dir,
                  allowed_uid=args.allow_uid,
                  max_requests=args.max_requests,
                  drop_ack_sequence=args.drop_ack_sequence)
            print('P3K_SERVER_EXITED')
        else:
            if (os.geteuid() == custodian_uid
                    or args.ledger_dir is not None
                    or args.allow_uid is not None
                    or args.max_requests is not None
                    or args.drop_ack_sequence is not None
                    or args.sequence is None):
                raise IntakeRefusal('P3K_CLIENT_ARGS_REFUSED')
            result = request(args.socket_dir / _SOCK_NAME, args.operation,
                             args.sequence, expected_uid=custodian_uid)
            print(json.dumps(result, sort_keys=True, separators=(',', ':')))
            return 0 if result['status'] == 'COMMITTED' else 3
    except OutcomeUnknown:
        print('P3K_ISSUE_OUTCOME_UNKNOWN')
        return 4
    except (IntakeRefusal, LabRefusal, sqlite3.Error, OSError,
            ValueError, socket.timeout) as exc:
        print(f'P3K_LAB_REFUSED: {type(exc).__name__}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
