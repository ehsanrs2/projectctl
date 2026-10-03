from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from projectctl.core.errors import ProjectLockError


@contextmanager
def project_lock(project_root: Path, name: str):
    lock_dir = project_root / ".projectctl" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{name}.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ProjectLockError(
            f"ProjectCTL operation {name!r} is already locked: {path}"
        ) from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
