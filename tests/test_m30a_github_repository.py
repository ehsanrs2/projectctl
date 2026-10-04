import subprocess
from pathlib import Path

from projectctl.integrations.github.repository import (
    infer_github_repository,
    normalize_github_repository,
    parse_github_repository,
)


def test_parse_supported_github_origin_forms():
    assert parse_github_repository("https://github.com/acme/widget.git") == "acme/widget"
    assert parse_github_repository("git@github.com:acme/widget.git") == "acme/widget"
    assert parse_github_repository("ssh://git@github.com/acme/widget.git") == "acme/widget"


def test_repository_identity_is_restricted_to_owner_repo():
    assert normalize_github_repository("acme/widget") == "acme/widget"
    assert normalize_github_repository("acme/widget?x=1") is None
    assert normalize_github_repository("https://github.com/acme/widget") is None
    assert parse_github_repository("https://example.com/acme/widget.git") is None


def test_infer_repository_reads_origin_without_network(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/widget.git"],
        check=True,
    )
    assert infer_github_repository(repo) == "acme/widget"
