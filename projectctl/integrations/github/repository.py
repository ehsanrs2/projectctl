from __future__ import annotations

import re
import subprocess
from pathlib import Path


_GITHUB_HTTPS = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SCP = re.compile(
    r"^(?:[^@]+@)?github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)
_GITHUB_SSH = re.compile(
    r"^ssh://(?:[^@]+@)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def parse_github_repository(remote_url: str | None) -> str | None:
    value = (remote_url or "").strip()
    if not value:
        return None
    for pattern in (_GITHUB_HTTPS, _GITHUB_SCP, _GITHUB_SSH):
        match = pattern.match(value)
        if match:
            owner = match.group("owner").strip()
            repo = match.group("repo").strip()
            if owner and repo:
                return f"{owner}/{repo}"
    return None


def infer_github_repository(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(project_root.resolve()), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return parse_github_repository(result.stdout)
