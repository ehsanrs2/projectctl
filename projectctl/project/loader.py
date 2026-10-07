from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.errors import ConfigurationError
from projectctl.schemas.config import (
    ProjectConfig,
    ProjectConfigV1,
    ProjectConfigV2,
    ProjectConfigV3,
    ProjectConfigV4,
    ProjectConfigV5,
    ProjectConfigV6,
    ProjectConfigV7,
    ProjectConfigV8,
)


def _delivery_for_legacy(provider: str, repository: str | None, code_transport: dict) -> dict:
    if (
        provider == "github"
        and repository
        and code_transport.get("mode") == "git_remote"
        and code_transport.get("remote_identity") == f"github.com/{repository}"
    ):
        return {"mode": "direct_git"}
    return {"mode": "local"}


def load_project_config(project_root: Path) -> ProjectConfig:
    path = project_root / ".projectctl" / "config.yaml"
    if not path.exists():
        raise ConfigurationError(f"Missing ProjectCTL config: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Project config must be a YAML mapping.")

        version = raw.get("schema_version", 1)
        if version == 9:
            return ProjectConfig.model_validate(raw)
        if version == 8:
            legacy = ProjectConfigV8.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded["orchestration"] = {"max_active_runs": 1}
            return ProjectConfig.model_validate(upgraded)
        if version == 7:
            legacy = ProjectConfigV7.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 6:
            legacy = ProjectConfigV6.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 5:
            legacy = ProjectConfigV5.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded["code_delivery"] = _delivery_for_legacy(
                legacy.task_store.provider,
                legacy.task_store.repository,
                upgraded["code_transport"],
            )
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 4:
            legacy = ProjectConfigV4.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            if legacy.task_store.provider == "github" and legacy.task_store.repository:
                upgraded["code_transport"] = {
                    "mode": "git_remote",
                    "remote_name": "origin",
                    "remote_identity": f"github.com/{legacy.task_store.repository}",
                }
            else:
                upgraded["code_transport"] = {"mode": "local"}
            upgraded["code_delivery"] = _delivery_for_legacy(
                upgraded["task_store"]["provider"],
                upgraded["task_store"].get("repository"),
                upgraded["code_transport"],
            )
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 3:
            legacy = ProjectConfigV3.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded["task_store"] = {
                "provider": legacy.task_store.provider,
                "repository": legacy.task_store.repository,
                "team": None,
                "cache_max_age_seconds": legacy.task_store.cache_max_age_seconds,
            }
            if legacy.task_store.provider == "github" and legacy.task_store.repository:
                upgraded["code_transport"] = {
                    "mode": "git_remote",
                    "remote_name": "origin",
                    "remote_identity": f"github.com/{legacy.task_store.repository}",
                }
            else:
                upgraded["code_transport"] = {"mode": "local"}
            upgraded["code_delivery"] = _delivery_for_legacy(
                upgraded["task_store"]["provider"],
                upgraded["task_store"].get("repository"),
                upgraded["code_transport"],
            )
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 2:
            legacy = ProjectConfigV2.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded["task_store"] = {
                "provider": legacy.task_store.provider,
                "repository": legacy.task_store.repository,
                "team": None,
                "cache_max_age_seconds": 30,
            }
            if legacy.task_store.provider == "github" and legacy.task_store.repository:
                upgraded["code_transport"] = {
                    "mode": "git_remote",
                    "remote_name": "origin",
                    "remote_identity": f"github.com/{legacy.task_store.repository}",
                }
            else:
                upgraded["code_transport"] = {"mode": "local"}
            upgraded["code_delivery"] = _delivery_for_legacy(
                upgraded["task_store"]["provider"],
                upgraded["task_store"].get("repository"),
                upgraded["code_transport"],
            )
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        if version == 1:
            legacy = ProjectConfigV1.model_validate(raw)
            upgraded = legacy.model_dump(mode="python")
            upgraded["schema_version"] = 9
            upgraded["task_store"] = {
                "provider": legacy.task_store.provider,
                "repository": None,
                "team": None,
                "cache_max_age_seconds": 30,
            }
            upgraded["code_transport"] = {"mode": "local"}
            upgraded["code_delivery"] = _delivery_for_legacy(
                upgraded["task_store"]["provider"],
                upgraded["task_store"].get("repository"),
                upgraded["code_transport"],
            )
            upgraded.setdefault("orchestration", {"max_active_runs": 1})
            return ProjectConfig.model_validate(upgraded)
        raise ConfigurationError(
            f"Unsupported project config schema version: {version!r}"
        )
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid project config: {exc}") from exc
