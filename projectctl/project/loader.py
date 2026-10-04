from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.errors import ConfigurationError
from projectctl.schemas.config import ProjectConfig, ProjectConfigV1, ProjectConfigV2


def load_project_config(project_root: Path) -> ProjectConfig:
    path = project_root / ".projectctl" / "config.yaml"
    if not path.exists():
        raise ConfigurationError(f"Missing ProjectCTL config: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Project config must be a YAML mapping.")

        version = raw.get("schema_version", 1)
        if version == 3:
            return ProjectConfig.model_validate(raw)
        if version == 2:
            legacy = ProjectConfigV2.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 3
            upgraded["task_store"] = {
                "provider": legacy.task_store.provider,
                "repository": legacy.task_store.repository,
                "cache_max_age_seconds": 30,
            }
            return ProjectConfig.model_validate(upgraded)
        if version == 1:
            legacy = ProjectConfigV1.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 3
            upgraded["task_store"] = {
                "provider": legacy.task_store.provider,
                "repository": None,
                "cache_max_age_seconds": 30,
            }
            return ProjectConfig.model_validate(upgraded)
        raise ConfigurationError(
            f"Unsupported project config schema version: {version!r}"
        )
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid project config: {exc}") from exc
