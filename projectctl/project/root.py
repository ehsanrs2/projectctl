import subprocess
from pathlib import Path

from projectctl.core.errors import RepositoryContractError


def git_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RepositoryContractError(f"Not inside a Git repository: {start}")
    return Path(proc.stdout.strip()).resolve()


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".projectctl").is_dir():
            return candidate
    return git_root(current)
