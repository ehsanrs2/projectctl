from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.core.errors import ClaimConflictError, ConfigurationError, TaskStoreError
from projectctl.git.remote import normalize_git_remote_identity
from projectctl.git.task_claim import GitRemoteTaskClaimer
from projectctl.integrations.execution_ownership import (
    require_project_execution_ready,
    resolve_execution_ownership,
)
from projectctl.integrations.local_claim import LocalTaskClaimer
from projectctl.project.loader import load_project_config
from projectctl.schemas.config import CodeTransportConfig, ProjectConfig, ProjectIdentity, TaskStoreConfig
from projectctl.schemas.task_claim import TaskClaimRequest


NOW = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)
BASE = "a" * 40
TEAM_ID = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"


def request(task_id="lin-ENG-1", token="a" * 32):
    return TaskClaimRequest(
        task_id=task_id,
        run_id="run-1",
        actor="projectctl:test",
        base_commit=BASE,
        integration_target_ref="main",
        claim_token=token,
        requested_at=NOW,
    )


def write_config(root: Path, *, provider: str, transport: CodeTransportConfig):
    ctl = root / ".projectctl"
    ctl.mkdir(exist_ok=True)
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider=provider,
            repository="acme/widget" if provider == "github" else None,
            team=TEAM_ID if provider == "linear" else None,
        ),
        code_transport=transport,
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


class FakeLease:
    def __init__(self, *, url="git@gitlab.com:acme/widget.git"):
        self.url = url
        self.current = {}
        self.remote_target = BASE
        self.releases = []

    def remote_url(self):
        return self.url

    def remote_branch(self, _branch_name):
        return self.remote_target

    def create_marker_commit(self, *, base_commit, message, timestamp):
        del base_commit, timestamp
        token = message.split('"claim_token":"', 1)[1].split('"', 1)[0]
        return ("1" if token.startswith("a") else "2") * 40

    def observe(self, ref):
        return self.current.get(ref)

    def acquire(self, *, ref, ownership_sha):
        if ref in self.current:
            return self.current[ref] == ownership_sha
        self.current[ref] = ownership_sha
        return True

    def release(self, *, ref, ownership_sha):
        current = self.current.get(ref)
        if current is None:
            return
        if current != ownership_sha:
            raise ClaimConflictError("ownership changed")
        self.releases.append((ref, ownership_sha))
        del self.current[ref]


def test_remote_identity_is_host_path_and_vendor_neutral():
    assert normalize_git_remote_identity(
        "git@gitlab.com:group/sub/repo.git"
    ) == "gitlab.com/group/sub/repo"
    assert normalize_git_remote_identity(
        "https://github.com/acme/widget.git"
    ) == "github.com/acme/widget"
    assert normalize_git_remote_identity(
        "ssh://git@git.example.internal/team/repo.git"
    ) == "git.example.internal/team/repo"


def test_transport_config_requires_explicit_remote_identity():
    assert CodeTransportConfig(mode="local").remote_name is None

    with pytest.raises(ValidationError, match="remote_name"):
        CodeTransportConfig(mode="git_remote")

    with pytest.raises(ValidationError, match="cannot configure"):
        CodeTransportConfig(
            mode="local",
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
        )


def test_local_claim_is_idempotent_conflict_safe_and_releasable(tmp_path: Path):
    claimer = LocalTaskClaimer(tmp_path, provider="linear")
    first = claimer.claim(request())
    same = claimer.claim(request())
    other = claimer.claim(request(token="b" * 32))

    assert first.acquired
    assert same.acquired
    assert not other.acquired
    assert first.ownership_ref and first.ownership_ref.startswith(
        ".projectctl/locks/task-claims/"
    )
    assert claimer.validate(first)

    reconciled = claimer.reconcile(request())
    assert reconciled.acquired

    claimer.release(first)
    assert not claimer.validate(first)


def test_local_release_refuses_replacement_owner(tmp_path: Path):
    claimer = LocalTaskClaimer(tmp_path, provider="linear")
    claim = claimer.claim(request())
    assert claim.ownership_ref is not None

    path = tmp_path / claim.ownership_ref
    path.write_text('{"replacement":"owner"}\n', encoding="utf-8")

    with pytest.raises(ClaimConflictError, match="ownership changed"):
        claimer.release(claim)


def test_generic_git_remote_claim_works_with_gitlab_identity(tmp_path: Path):
    lease = FakeLease()
    claimer = GitRemoteTaskClaimer(
        tmp_path,
        provider="linear",
        remote_name="origin",
        remote_identity="gitlab.com/acme/widget",
        lease=lease,
    )

    claim = claimer.claim(request())

    assert claim.acquired
    assert claim.provider == "linear"
    assert claim.repository == "gitlab.com/acme/widget"
    assert claim.ownership_ref is not None
    assert claim.ownership_ref.startswith("refs/heads/projectctl/claims/linear/")
    assert claimer.validate(claim)

    claimer.release(claim)
    assert lease.current == {}


def test_generic_git_remote_claim_rejects_remote_substitution(tmp_path: Path):
    claimer = GitRemoteTaskClaimer(
        tmp_path,
        provider="linear",
        remote_name="origin",
        remote_identity="gitlab.com/acme/widget",
        lease=FakeLease(url="git@github.com:acme/widget.git"),
    )

    with pytest.raises(TaskStoreError, match="remote identity"):
        claimer.claim(request())


def test_linear_local_transport_resolves_local_ownership(tmp_path: Path):
    write_config(
        tmp_path,
        provider="linear",
        transport=CodeTransportConfig(mode="local"),
    )

    ownership = resolve_execution_ownership(tmp_path)

    assert ownership.policy.strategy == "local_lock"
    assert ownership.policy.scope == "local"
    assert ownership.policy.task_provider == "linear"


def test_linear_gitlab_transport_resolves_distributed_git_ownership(
    tmp_path: Path,
    monkeypatch,
):
    write_config(
        tmp_path,
        provider="linear",
        transport=CodeTransportConfig(
            mode="git_remote",
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
        ),
    )

    class FakeGenericClaimer:
        def __init__(self, _root, *, provider, remote_name, remote_identity):
            self.provider = provider
            self.remote_name = remote_name
            self.remote_identity = remote_identity

    monkeypatch.setattr(
        "projectctl.integrations.execution_ownership.GitRemoteTaskClaimer",
        FakeGenericClaimer,
    )

    ownership = resolve_execution_ownership(tmp_path)

    assert ownership.policy.strategy == "git_ref_lease"
    assert ownership.policy.scope == "distributed"
    assert ownership.policy.remote_identity == "gitlab.com/acme/widget"
    assert ownership.claimer.provider == "linear"


def test_linear_is_still_not_execution_ready_after_ownership_is_decoupled(tmp_path: Path):
    write_config(
        tmp_path,
        provider="linear",
        transport=CodeTransportConfig(mode="local"),
    )

    with pytest.raises(ConfigurationError, match="block_for_decision, complete"):
        require_project_execution_ready(tmp_path)


def test_project_config_v4_github_migrates_to_remote_transport(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.project_config",
                "schema_version": 4,
                "project": {"id": "demo"},
                "task_store": {
                    "provider": "github",
                    "repository": "acme/widget",
                    "team": None,
                    "cache_max_age_seconds": 30,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 5
    assert config.code_transport.mode == "git_remote"
    assert config.code_transport.remote_name == "origin"
    assert config.code_transport.remote_identity == "github.com/acme/widget"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 4


def test_project_config_v4_linear_migrates_to_local_transport(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.project_config",
                "schema_version": 4,
                "project": {"id": "demo"},
                "task_store": {
                    "provider": "linear",
                    "repository": None,
                    "team": TEAM_ID,
                    "cache_max_age_seconds": 30,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 5
    assert config.code_transport.mode == "local"
