from __future__ import annotations

import json
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.errors import ProjectLockError


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _read_lock(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _can_reclaim(path: Path, *, hostname: str) -> bool:
    metadata = _read_lock(path)
    if metadata is None:
        return False
    if metadata.get("hostname") != hostname:
        return False
    try:
        pid = int(metadata.get("pid"))
    except (TypeError, ValueError):
        return False
    return not _pid_alive(pid)


@contextmanager
def project_lock(project_root: Path, name: str):
    lock_dir = project_root / ".projectctl" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{name}.lock"
    hostname = socket.gethostname()
    token = uuid.uuid4().hex
    metadata = {
        "pid": os.getpid(),
        "hostname": hostname,
        "token": token,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }

    fd = None
    metadata_written = False
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError as exc:
            if attempt == 0 and _can_reclaim(path, hostname=hostname):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            owner = _read_lock(path)
            detail = f" owner={owner}" if owner is not None else ""
            raise ProjectLockError(
                f"ProjectCTL operation {name!r} is already locked: {path}.{detail}"
            ) from exc

    if fd is None:
        raise ProjectLockError(f"Could not acquire ProjectCTL lock {path}.")

    try:
        os.write(fd, json.dumps(metadata, sort_keys=True).encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = None
        metadata_written = True
        yield
    finally:
        if fd is not None:
            os.close(fd)
        current = _read_lock(path)
        if (current is not None and current.get("token") == token) or not metadata_written:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
