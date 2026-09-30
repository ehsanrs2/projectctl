from pathlib import Path

import pytest

from projectctl.core.errors import UnsafePathError
from projectctl.core.paths import resolve_inside_repo, validate_repo_path


@pytest.mark.parametrize("value", ["/etc/passwd", "../secret", "foo/../../bar", r"foo\\bar", "~/secret"])
def test_rejects_unsafe_repo_paths(value):
    with pytest.raises(ValueError):
        validate_repo_path(value)


def test_symlink_escape_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir(); outside.mkdir()
    (repo / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        resolve_inside_repo(repo, "link/file.txt")
