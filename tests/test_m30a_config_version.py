from pathlib import Path

import yaml

from projectctl.project.loader import load_project_config
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import ProjectConfig, ProjectConfigV1


def test_project_config_v1_is_loaded_as_v2_without_rewrite(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.project_config",
                "schema_version": 1,
                "project": {"id": "demo"},
                "task_store": {"provider": "beads"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 2
    assert config.task_store.provider == "beads"
    assert config.task_store.repository is None
    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert "repository" not in persisted["task_store"]


def test_project_config_v1_and_v2_are_both_public():
    assert PUBLIC_SCHEMAS["project-config.v1.schema.json"] is ProjectConfigV1
    assert PUBLIC_SCHEMAS["project-config.v2.schema.json"] is ProjectConfig
    assert ProjectConfigV1.model_fields["schema_version"].default == 1
    assert ProjectConfig.model_fields["schema_version"].default == 2
