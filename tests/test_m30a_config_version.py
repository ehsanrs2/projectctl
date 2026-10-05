from pathlib import Path

import yaml

from projectctl.project.loader import load_project_config
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import ProjectConfig, ProjectConfigV1, ProjectConfigV2, ProjectConfigV3, ProjectConfigV4, ProjectConfigV5


def test_project_config_v1_is_loaded_as_v6_without_rewrite(tmp_path: Path):
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

    assert config.schema_version == 6
    assert config.task_store.provider == "beads"
    assert config.task_store.repository is None
    assert config.task_store.team is None
    assert config.task_store.cache_max_age_seconds == 30
    assert config.code_transport.mode == "local"
    assert config.code_transport.remote_name is None
    assert config.code_delivery.mode == "local"
    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert "repository" not in persisted["task_store"]


def test_project_config_v1_through_v6_are_public():
    assert PUBLIC_SCHEMAS["project-config.v1.schema.json"] is ProjectConfigV1
    assert PUBLIC_SCHEMAS["project-config.v2.schema.json"] is ProjectConfigV2
    assert PUBLIC_SCHEMAS["project-config.v3.schema.json"] is ProjectConfigV3
    assert PUBLIC_SCHEMAS["project-config.v4.schema.json"] is ProjectConfigV4
    assert PUBLIC_SCHEMAS["project-config.v5.schema.json"] is ProjectConfigV5
    assert PUBLIC_SCHEMAS["project-config.v6.schema.json"] is ProjectConfig
    assert ProjectConfigV1.model_fields["schema_version"].default == 1
    assert ProjectConfigV2.model_fields["schema_version"].default == 2
    assert ProjectConfigV3.model_fields["schema_version"].default == 3
    assert ProjectConfigV4.model_fields["schema_version"].default == 4
    assert ProjectConfigV5.model_fields["schema_version"].default == 5
    assert ProjectConfig.model_fields["schema_version"].default == 6
