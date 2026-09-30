from pathlib import Path, PurePosixPath

from projectctl.core.errors import UnsafePathError


def validate_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Repository path must be a non-empty string.")
    if "\\" in value:
        raise ValueError("Repository paths must use POSIX '/' separators.")
    if value.startswith("~"):
        raise ValueError("Repository paths cannot use home expansion.")

    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("Repository path must be relative.")
    if ".." in path.parts:
        raise ValueError("Repository path cannot escape repository root.")
    if "." in path.parts:
        # Normalize explicit current-directory segments rather than carry ambiguity.
        path = PurePosixPath(*[p for p in path.parts if p != "."])
    return path.as_posix()


def resolve_inside_repo(repo_root: Path, relative: str, *, must_exist: bool = False) -> Path:
    try:
        safe_relative = validate_repo_path(relative)
    except ValueError as exc:
        raise UnsafePathError(str(exc)) from exc

    root = repo_root.resolve()
    candidate = (root / safe_relative).resolve(strict=must_exist)
    if not candidate.is_relative_to(root):
        raise UnsafePathError(f"Path escapes repository root: {relative}")
    return candidate
