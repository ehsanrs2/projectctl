from pathlib import Path

import json
import yaml
import pytest
from typer.testing import CliRunner

from projectctl.cli.app import app
from projectctl.core.enums import CapabilityState
from projectctl.core.errors import ConfigurationError
from projectctl.integrations.task_authority import (
    require_task_authority_execution_ready,
    task_authority_capabilities,
    task_authority_capabilities_for_provider,
)
from projectctl.project.ownership import DEFAULT_OWNERSHIP
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import ProjectConfig, ProjectIdentity, TaskStoreConfig
from projectctl.schemas.task_authority import TaskAuthorityCapabilities
from projectctl.verification.diff import SYSTEM_PROTECTED_PATHS

runner = CliRunner()


def write_config(root: Path, provider: str, repository: str | None = None) -> None:
    ctl = root / ".projectctl"
    ctl.mkdir(parents=True)
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(provider=provider, repository=repository),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


def test_static_capabilities_do_not_require_provider_runtime(tmp_path: Path):
    write_config(tmp_path, "github", "acme/widget")

    capabilities = task_authority_capabilities(tmp_path)

    assert capabilities.provider == "github"
    assert capabilities.read == CapabilityState.SUPPORTED
    assert capabilities.claim == CapabilityState.SUPPORTED
    assert capabilities.release == CapabilityState.SUPPORTED
    assert capabilities.block_for_decision == CapabilityState.UNSUPPORTED
    assert capabilities.complete == CapabilityState.UNSUPPORTED


def test_beads_is_execution_ready_and_github_is_not(tmp_path: Path):
    beads = task_authority_capabilities_for_provider("beads")
    assert all(
        getattr(beads, field) == CapabilityState.SUPPORTED
        for field in [
            "read",
            "claim",
            "release",
            "block_for_decision",
            "complete",
        ]
    )

    write_config(tmp_path, "github", "acme/widget")
    with pytest.raises(ConfigurationError, match="not execution-ready"):
        require_task_authority_execution_ready(tmp_path)


def test_task_authority_cli_is_machine_readable_without_provider_probe(tmp_path: Path):
    write_config(tmp_path, "github", "acme/widget")

    result = runner.invoke(
        app,
        ["task-authority", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_kind"] == "projectctl.task_authority_capabilities"
    assert payload["provider"] == "github"
    assert payload["claim"] == "supported"
    assert payload["release"] == "supported"
    assert payload["complete"] == "unsupported"


def test_task_authority_capability_schema_is_public():
    assert (
        PUBLIC_SCHEMAS["task-authority-capabilities.v1.schema.json"]
        is TaskAuthorityCapabilities
    )


def test_application_layer_has_no_task_provider_implementation_imports():
    application = Path(__file__).parents[1] / "projectctl" / "application"
    forbidden = (
        "projectctl.integrations.beads",
        "projectctl.integrations.github",
        'provider == "beads"',
        'provider == "github"',
    )

    offenders: list[str] = []
    for path in sorted(application.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for import_path in forbidden:
            if import_path in text:
                offenders.append(f"{path.name}: {import_path}")

    assert offenders == []



def test_architecture_blueprint_is_human_owned_and_worker_protected():
    assert "docs/PROJECTCTL_BLUEPRINT.md" in DEFAULT_OWNERSHIP
    assert "docs/PROJECTCTL_BLUEPRINT.md" in SYSTEM_PROTECTED_PATHS
