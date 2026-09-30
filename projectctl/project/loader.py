from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.errors import ConfigurationError
from projectctl.schemas.config import ProjectConfig


def load_project_config(project_root: Path) -> ProjectConfig:
    path = project_root / ".projectctl" / "config.yaml"
    if not path.exists():
        raise ConfigurationError(f"Missing ProjectCTL config: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Project config must be a YAML mapping.")
        return ProjectConfig.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid project config: {exc}") from exc
