"""M6.0 P3j: bounded synthetic Unix peer-credential intake, lab-only.

No arbitrary payload bytes, project data, signing, or service installation.
This process is *not* an authenticated source-epoch producer; Linux UID is
only a local IPC admission claim. Requires an external trusted launch owner.
"""
from __future__ import annotations

import argparse
import json
import pwd
import re
import sqlite3
import os
from pathlib import Path
import socket
import stat
import struct
import sys
from typing import Any

if __package__:
    from scripts.p3i_synthetic_sqlite_custody_lab import LabRefusal, commit, inspect
else:
    # When installed beside a reviewed, root-owned copy of P3i, even -I can
    # resolve only this explicit adjacent directory. This is not a proof of
    # the ancestry or immutability of the installed program.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from p3i_synthetic_sqlite_custody_lab import LabRefusal, commit, inspect

_SOCK_NAME = 'intake.sock'
_MAX_BYTES = 128
_ACK = 'SYNTHETIC_DISPOSABLE_LAB'


class IntakeRefusal(ValueError):
    """Inadmissible peer, frame, socket or launch contract."""


def _private_socket_dir(folder: Path) -> None:
    entry = folder.lstat()
    if (not stat.S_ISDIR(entry.st_mode)
            or entry.st_uid != os.geteuid()
            or stat.S_IMODE(entry.st_mode) != 0o711):
        raise IntakeRefusal('P3J_SOCKET_DIRECTORY_OWNER_OR_MODE_REFUSED')


def _peer_uid(conn: socket.socket) -> int:
    if not hasattr(socket, 'SO_PEERCRED'):
        raise IntakeRefusal('P3J_SO_PEERCRED_REQUIRED')
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                          struct.calcsize('3i'))
    _pid, uid, _gid = struct.unpack('3i', raw)
    return uid


def _parse_frame(raw: bytes) -> int:
    if not raw.endswith(b'\n') or len(raw) > _MAX_BYTES or len(raw) < 2:
        raise IntakeRefusal('P3J_FRAME_REFUSED')
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IntakeRefusal('P3J_DUPLICATE_JSON_KEY_REFUSED')
            result[key] = value
        return result

    try:
        obj: Any = json.loads(raw[:-1].decode('ascii'),
                              object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError) as exc:
        raise IntakeRefusal('P3J_JSON_REFUSED') from exc
    if (type(obj) is not dict or set(obj) != {'v', 'op', 'sequence'}
            or type(obj['v']) is not int or obj['v'] != 1
            or obj['op'] != 'issue' or type(obj['sequence']) is not int
            or not (1 <= obj['sequence'] <= 1_000_000)):
        raise IntakeRefusal('P3J_SCHEMA_REFUSED')
    return obj['sequence']


def _response(conn: socket.socket, code: str, digest: str | None = None) -> None:
    obj = {'status': code}
    if digest is not None:
        obj['sha256'] = digest
    try:
        conn.sendall(json.dumps(obj, sort_keys=True,
                                separators=(',', ':')).encode('ascii') + b'\n')
    except (OSError, socket.timeout):
        # Loss of the ACK does not reverse an already-committed receipt.
        pass


def serve(socket_dir: Path, ledger_dir: Path, *, allowed_uid: int,
          max_requests: int, ready=None) -> None:
    """Process at most max_requests sequential local requests, then exit.

    Caller must independently arrange that this code and launch config are
    administrator controlled, that ledger_dir is Custodian-owned, and that
    the admitted writer cannot impersonate or control the Custodian UID.
    """
    if not (0 <= allowed_uid < 2**32 and 1 <= max_requests <= 16):
        raise IntakeRefusal('P3J_LAUNCH_LIMITS_REFUSED')
    _private_socket_dir(socket_dir)
    inspect(ledger_dir)  # must be existing, not silently initialized
    path = socket_dir / _SOCK_NAME
    if path.exists() or path.is_symlink():
        raise IntakeRefusal('P3J_SOCKET_ALREADY_EXISTS')
    if len(os.fsencode(path)) >= 105:
        raise IntakeRefusal('P3J_SOCKET_PATH_TOO_LONG')

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
                            raise IntakeRefusal('P3J_PEER_UID_REFUSED')
                        frame = bytearray()
                        while len(frame) <= _MAX_BYTES:
                            block = conn.recv(_MAX_BYTES + 1 - len(frame))
                            if not block:
                                break
                            frame.extend(block)
                        sequence = _parse_frame(bytes(frame))
                        digest = commit(ledger_dir, sequence)
                    except (IntakeRefusal, LabRefusal, sqlite3.Error, OSError,
                            ValueError, socket.timeout):
                        _response(conn, 'REFUSED')
                    else:
                        _response(conn, 'COMMITTED', digest)
        finally:
            try:
                current = path.lstat()
                if (stat.S_ISSOCK(current.st_mode)
                        and (current.st_dev, current.st_ino)
                        == (identity.st_dev, identity.st_ino)):
                    path.unlink()
            except FileNotFoundError:
                pass


def request(path: Path, sequence: int, *, expected_uid: int | None = None) -> dict:
    """Lab client; the caller's sequence is not provenance/authentication."""
    raw = json.dumps({'v': 1, 'op': 'issue', 'sequence': sequence},
                     separators=(',', ':')).encode('ascii') + b'\n'
    if len(raw) > _MAX_BYTES:
        raise IntakeRefusal('P3J_CLIENT_TOO_LARGE')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(str(path))
        if expected_uid is not None and _peer_uid(conn) != expected_uid:
            raise IntakeRefusal('P3J_SERVER_UID_REFUSED')
        conn.sendall(raw)
        conn.shutdown(socket.SHUT_WR)
        response = conn.recv(256)
    if not response.endswith(b'\n') or len(response) > 256:
        raise IntakeRefusal('P3J_RESPONSE_INVALID')
    parsed = json.loads(response)
    if (type(parsed) is not dict
            or parsed.get('status') not in ('COMMITTED', 'REFUSED')):
        raise IntakeRefusal('P3J_RESPONSE_SCHEMA_INVALID')
    if parsed['status'] == 'COMMITTED':
        if (set(parsed) != {'status', 'sha256'}
                or type(parsed['sha256']) is not str
                or re.fullmatch(r'[0-9a-f]{64}', parsed['sha256']) is None):
            raise IntakeRefusal('P3J_RESPONSE_DIGEST_INVALID')
    elif set(parsed) != {'status'}:
        raise IntakeRefusal('P3J_REFUSAL_RESPONSE_INVALID')
    return parsed


def _lab_path(path: Path, prefix: str, mode: int | None,
              owner_uid: int | None = None) -> bool:
    if not (path.is_absolute() and path.parent == Path('/var/tmp')
            and path.name.startswith(prefix) and len(path.name) <= 64):
        return False
    try:
        entry = path.lstat()
    except OSError:
        return False
    return (stat.S_ISDIR(entry.st_mode)
            and (owner_uid is None or entry.st_uid == owner_uid)
            and (mode is None or stat.S_IMODE(entry.st_mode) == mode))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('serve', 'request'))
    parser.add_argument('--socket-dir', required=True, type=Path)
    parser.add_argument('--ledger-dir', type=Path)
    parser.add_argument('--allow-uid', type=int)
    parser.add_argument('--max-requests', type=int)
    parser.add_argument('--sequence', type=int)
    parser.add_argument('--acknowledge', choices=(_ACK,))
    args = parser.parse_args(argv)
    try:
        custodian_uid = pwd.getpwnam('p3-custodian').pw_uid
    except KeyError:
        print('P3J_LAB_REFUSED')
        return 2
    if (os.geteuid() == 0 or os.getuid() != os.geteuid()
            or args.acknowledge != _ACK
            or not _lab_path(args.socket_dir, 'projectctl-p3j-',
                             0o711, custodian_uid)):
        print('P3J_LAB_REFUSED')
        return 2
    try:
        if args.operation == 'serve':
            if (os.geteuid() != custodian_uid or args.allow_uid == custodian_uid
                    or args.ledger_dir is None or args.allow_uid is None
                    or args.max_requests is None or args.sequence is not None
                    or not _lab_path(args.ledger_dir, 'projectctl-p3i-', 0o700, custodian_uid)):
                raise IntakeRefusal('P3J_SERVER_ARGS_REFUSED')
            serve(args.socket_dir, args.ledger_dir,
                  allowed_uid=args.allow_uid, max_requests=args.max_requests)
            print('P3J_SERVER_EXITED')
        else:
            if (args.sequence is None or args.ledger_dir is not None
                    or args.allow_uid is not None or args.max_requests is not None):
                raise IntakeRefusal('P3J_CLIENT_ARGS_REFUSED')
            if os.geteuid() == custodian_uid:
                raise IntakeRefusal('P3J_CLIENT_SAME_AS_CUSTODIAN_REFUSED')
            result = request(args.socket_dir / _SOCK_NAME, args.sequence,
                             expected_uid=custodian_uid)
            print(json.dumps(result, sort_keys=True, separators=(',', ':')))
            return 0 if result['status'] == 'COMMITTED' else 3
    except (IntakeRefusal, LabRefusal, sqlite3.Error, OSError, ValueError, socket.timeout) as exc:
        print(f'P3J_LAB_REFUSED: {type(exc).__name__}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
