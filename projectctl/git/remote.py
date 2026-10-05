from __future__ import annotations

import re
from urllib.parse import urlsplit

from projectctl.core.errors import TaskStoreError


_SCP_LIKE = re.compile(r"^(?:(?P<user>[^@/:]+)@)?(?P<host>[^/:]+):(?P<path>.+)$")


def normalize_git_remote_identity(value: str | None) -> str | None:
    """Normalize a network Git remote to host/path without credentials/scheme.

    Examples:
      git@github.com:acme/widget.git -> github.com/acme/widget
      https://gitlab.com/acme/widget.git -> gitlab.com/acme/widget
      ssh://git@example.com/group/repo.git -> example.com/group/repo
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    host = ""
    path = ""

    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https", "ssh", "git"}:
            raise TaskStoreError(
                f"Unsupported network Git remote scheme: {parsed.scheme!r}."
            )
        host = (parsed.hostname or "").strip().casefold()
        path = parsed.path.lstrip("/")
    else:
        match = _SCP_LIKE.match(raw)
        if match is None:
            raise TaskStoreError(
                "Git remote identity requires a network remote URL; "
                "local filesystem remotes are not supported by git_remote mode."
            )
        host = str(match.group("host") or "").strip().casefold()
        path = str(match.group("path") or "").lstrip("/")

    if path.endswith(".git"):
        path = path[:-4]
    path = "/".join(part for part in path.split("/") if part).strip()
    if not host or not path or ".." in path.split("/"):
        raise TaskStoreError(f"Invalid Git remote identity: {value!r}.")
    return f"{host}/{path}"
