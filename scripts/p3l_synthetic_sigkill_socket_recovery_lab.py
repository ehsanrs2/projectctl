"""M6.0 P3l: synthetic SIGKILL + explicit Unix socket recovery.

Disposable Linux/KVM engineering lab ONLY. Host/root are trusted.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import stat
import sys

if __package__:
    from scripts.p3i_synthetic_sqlite_custody_lab import LabRefusal, _synthetic_bytes, commit, inspect
    from scripts.p3k_synthetic_ack_recovery_lab import (
        IntakeRefusal, OutcomeUnknown, _lab_path, _peer_uid,
        _private_socket_dir, _parse_frame, _send, lookup, request,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from p3i_synthetic_sqlite_custody_lab import LabRefusal, _synthetic_bytes, commit, inspect
    from p3k_synthetic_ack_recovery_lab import (
        IntakeRefusal, OutcomeUnknown, _lab_path, _peer_uid,
        _private_socket_dir, _parse_frame, _send, lookup, request,
    )

_SOCKET = 'intake.sock'
_LOCK = '.custodian-owner.lock'
_ACK = 'SYNTHETIC_DISPOSABLE_LAB'
_MAX_FRAME = 128


@contextmanager
def _owner_lock(folder: Path):
    """Kernel-released cross-process lock; never unlink its persistent inode."""
    _private_socket_dir(folder)
    if not hasattr(os, 'O_NOFOLLOW'):
        raise IntakeRefusal('P3L_NOFOLLOW_REQUIRED')
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(folder / _LOCK, flags, 0o600)
    try:
        entry = os.fstat(fd)
        named = (folder / _LOCK).lstat()
        if (not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) != 0o600
                or entry.st_nlink != 1
                or (entry.st_dev, entry.st_ino) != (named.st_dev, named.st_ino)):
            raise IntakeRefusal('P3L_OWNER_LOCK_UNSAFE')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IntakeRefusal('P3L_ACTIVE_OWNER_REFUSED') from exc
        yield
    finally:
        os.close(fd)


def _recover_socket(path: Path, *, explicitly_allowed: bool) -> bool:
    """Under the owner lock, unlink only a verified, disconnected socket."""
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False
    if not explicitly_allowed:
        raise IntakeRefusal('P3L_STALE_RECOVERY_REQUIRES_OPT_IN')
    if (not stat.S_ISSOCK(entry.st_mode)
            or entry.st_uid != os.geteuid()
            or stat.S_IMODE(entry.st_mode) != 0o666
            or entry.st_nlink != 1):
        raise IntakeRefusal('P3L_UNSAFE_SOCKET_REFUSED')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(str(path))
        except OSError as exc:
            if exc.errno != errno.ECONNREFUSED:
                raise IntakeRefusal('P3L_SOCKET_LIVENESS_UNCERTAIN') from exc
        else:
            raise IntakeRefusal('P3L_SOCKET_HAS_LISTENER_REFUSED')
    current = path.lstat()
    if (not stat.S_ISSOCK(current.st_mode)
            or (current.st_dev, current.st_ino) != (entry.st_dev, entry.st_ino)
            or current.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) != 0o666):
        raise IntakeRefusal('P3L_SOCKET_CHANGED_REFUSED')
    path.unlink()
    return True


def serve(socket_dir: Path, ledger_dir: Path, *, allowed_uid: int,
          max_requests: int, recover_stale: bool = False,
          crash_before_sequence: int | None = None,
          crash_after_sequence: int | None = None, ready=None) -> None:
    """Process at most 16 requests; optional self-SIGKILL within P3i commit."""
    if (not hasattr(socket, 'SO_PEERCRED')
            or not (0 <= allowed_uid < 2**32 and 1 <= max_requests <= 16)
            or (crash_before_sequence is not None
                and crash_after_sequence is not None)):
        raise IntakeRefusal('P3L_LIMITS_REFUSED')
    for value in (crash_before_sequence, crash_after_sequence):
        if value is not None:
            _synthetic_bytes(value)
    if ((crash_before_sequence is not None
         or crash_after_sequence is not None) and max_requests != 1):
        raise IntakeRefusal('P3L_FAULT_REQUIRES_ONE_REQUEST')
    _private_socket_dir(socket_dir)
    socket_path = socket_dir / _SOCKET
    if len(os.fsencode(socket_path)) >= 105:
        raise IntakeRefusal('P3L_SOCKET_PATH_TOO_LONG')
    with _owner_lock(socket_dir):
        inspect(ledger_dir)  # verify and recover hot SQLite journal if needed
        _recover_socket(socket_path, explicitly_allowed=recover_stale)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(socket_path))
            original = socket_path.lstat()
            try:
                os.chmod(socket_path, 0o666)
                listener.listen(4)
                if ready is not None:
                    ready.set()
                for _ in range(max_requests):
                    conn, _ = listener.accept()
                    with conn:
                        conn.settimeout(2)
                        try:
                            if _peer_uid(conn) != allowed_uid:
                                raise IntakeRefusal('P3L_PEER_UID_REFUSED')
                            frame = bytearray()
                            while len(frame) <= _MAX_FRAME:
                                data = conn.recv(_MAX_FRAME + 1 - len(frame))
                                if not data:
                                    break
                                frame.extend(data)
                            operation, sequence = _parse_frame(bytes(frame))
                            if operation == 'lookup':
                                result = lookup(ledger_dir, sequence)
                            else:
                                digest = commit(
                                    ledger_dir, sequence,
                                    crash_before=(sequence == crash_before_sequence),
                                    crash_after=(sequence == crash_after_sequence),
                                )
                                result = {'status': 'COMMITTED', 'sha256': digest}
                        except (IntakeRefusal, LabRefusal, sqlite3.Error,
                                OSError, ValueError, socket.timeout):
                            _send(conn, {'status': 'REFUSED'})
                        else:
                            _send(conn, result)
            finally:
                try:
                    current = socket_path.lstat()
                    if (stat.S_ISSOCK(current.st_mode)
                            and (current.st_dev, current.st_ino)
                            == (original.st_dev, original.st_ino)):
                        socket_path.unlink()
                except FileNotFoundError:
                    pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('serve', 'issue', 'lookup'))
    parser.add_argument('--socket-dir', required=True, type=Path)
    parser.add_argument('--ledger-dir', type=Path)
    parser.add_argument('--allow-uid', type=int)
    parser.add_argument('--max-requests', type=int)
    parser.add_argument('--recover-stale-socket', action='store_true')
    parser.add_argument('--crash-before-sequence', type=int)
    parser.add_argument('--crash-after-sequence', type=int)
    parser.add_argument('--sequence', type=int)
    parser.add_argument('--acknowledge', choices=(_ACK,))
    args = parser.parse_args(argv)
    try:
        custodian_uid = pwd.getpwnam('p3-custodian').pw_uid
    except KeyError:
        print('P3L_LAB_REFUSED')
        return 2
    if (os.geteuid() == 0 or os.getuid() != os.geteuid()
            or args.acknowledge != _ACK
            or not _lab_path(args.socket_dir, 'projectctl-p3l-',
                             0o711, custodian_uid)):
        print('P3L_LAB_REFUSED')
        return 2
    try:
        if args.operation == 'serve':
            if (os.geteuid() != custodian_uid
                    or args.allow_uid is None or args.allow_uid == custodian_uid
                    or args.ledger_dir is None or args.max_requests is None
                    or args.sequence is not None
                    or not _lab_path(args.ledger_dir, 'projectctl-p3i-',
                                     0o700, custodian_uid)):
                raise IntakeRefusal('P3L_SERVER_ARGS_REFUSED')
            serve(args.socket_dir, args.ledger_dir,
                  allowed_uid=args.allow_uid,
                  max_requests=args.max_requests,
                  recover_stale=args.recover_stale_socket,
                  crash_before_sequence=args.crash_before_sequence,
                  crash_after_sequence=args.crash_after_sequence)
            print('P3L_SERVER_EXITED')
        else:
            if (os.geteuid() == custodian_uid
                    or args.ledger_dir is not None or args.allow_uid is not None
                    or args.max_requests is not None or args.recover_stale_socket
                    or args.crash_before_sequence is not None
                    or args.crash_after_sequence is not None
                    or args.sequence is None):
                raise IntakeRefusal('P3L_CLIENT_ARGS_REFUSED')
            result = request(args.socket_dir / _SOCKET, args.operation,
                             args.sequence, expected_uid=custodian_uid)
            print(json.dumps(result, sort_keys=True, separators=(',', ':')))
            return 0 if result['status'] == 'COMMITTED' else 3
    except OutcomeUnknown:
        print('P3L_ISSUE_OUTCOME_UNKNOWN')
        return 4
    except (IntakeRefusal, LabRefusal, sqlite3.Error, OSError,
            ValueError, socket.timeout) as exc:
        print(f'P3L_LAB_REFUSED: {type(exc).__name__}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
