from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.core.errors import ConfigurationError
from projectctl.execution_scope.catalog import (
    load_execution_scope_catalog,
    parse_execution_scope_catalog_bytes,
    resolve_execution_scope_catalog,
    task_execution_scope,
)
from projectctl.project.loader import load_project_config
from projectctl.schema_export import PUBLIC_SCHEMAS
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
    ProjectConfigV9,
    ProjectIdentity,
)
from projectctl.schemas.execution_scope import ExecutionScopeCatalog, ExecutionTaskScope
from projectctl.schemas.parallel import ParallelScopeCatalog


def _raw_scope(kind: str) -> bytes:
    return yaml.safe_dump(
        {
            "schema_kind": kind,
            "schema_version": 1,
            "tasks": {
                "task-1": {
                    "task_id": "task-1",
                    "inputs": [{"path": "src/app.py", "kind": "exact"}],
                    "writes": [{"path": "src", "kind": "tree"}],
                    "resources": ["parser"],
                }
            },
        },
        sort_keys=False,
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("filename", "kind", "source"),
    [
        ("projectctl.scope.yaml", "projectctl.execution_scope_catalog", "canonical"),
        ("projectctl.parallel.yaml", "projectctl.parallel_scope_catalog", "legacy"),
    ],
)
def test_scope_catalog_single_authority_and_raw_snapshot(
    tmp_path: Path, filename: str, kind: str, source: str
):
    raw = _raw_scope(kind)
    (tmp_path / filename).write_bytes(raw)

    snapshot = resolve_execution_scope_catalog(tmp_path)
    assert snapshot.source == source
    assert snapshot.path == tmp_path / filename
    assert snapshot.raw_bytes == raw
    assert snapshot.raw_digest == hashlib.sha256(raw).hexdigest()
    assert snapshot.catalog is not None
    assert snapshot.catalog.schema_kind == "projectctl.execution_scope_catalog"
    assert task_execution_scope(tmp_path, "task-1").resources == ["parser"]
    assert load_execution_scope_catalog(tmp_path) == snapshot.catalog


def test_legacy_scope_conversion_preserves_task_digest(tmp_path: Path):
    legacy = ParallelScopeCatalog.model_validate(
        yaml.safe_load(_raw_scope("projectctl.parallel_scope_catalog"))
    )
    (tmp_path / "projectctl.parallel.yaml").write_bytes(
        _raw_scope("projectctl.parallel_scope_catalog")
    )
    generic = task_execution_scope(tmp_path, "task-1")
    assert digest(generic) == digest(legacy.tasks["task-1"])


def test_no_catalog_is_explicitly_absent(tmp_path: Path):
    snapshot = resolve_execution_scope_catalog(tmp_path)
    assert snapshot.source == "absent"
    assert snapshot.path is None
    assert snapshot.raw_bytes is None
    assert snapshot.raw_digest is None
    assert load_execution_scope_catalog(tmp_path) is None
    with pytest.raises(ConfigurationError, match="Missing human-managed"):
        task_execution_scope(tmp_path, "task-1")


def test_missing_task_fails_closed(tmp_path: Path):
    (tmp_path / "projectctl.scope.yaml").write_bytes(
        _raw_scope("projectctl.execution_scope_catalog")
    )
    with pytest.raises(ConfigurationError, match="no declared scope"):
        task_execution_scope(tmp_path, "task-2")


def test_dual_authority_is_rejected_even_if_equivalent(tmp_path: Path):
    (tmp_path / "projectctl.scope.yaml").write_bytes(
        _raw_scope("projectctl.execution_scope_catalog")
    )
    (tmp_path / "projectctl.parallel.yaml").write_bytes(
        _raw_scope("projectctl.parallel_scope_catalog")
    )
    with pytest.raises(ConfigurationError, match="Both projectctl"):
        resolve_execution_scope_catalog(tmp_path)


@pytest.mark.parametrize("filename", ["projectctl.scope.yaml", "projectctl.parallel.yaml"])
def test_scope_authority_symlinks_fail_closed(tmp_path: Path, filename: str):
    (tmp_path / filename).symlink_to(tmp_path / "missing-target.yaml")
    with pytest.raises(ConfigurationError, match="symlinked"):
        resolve_execution_scope_catalog(tmp_path)


@pytest.mark.parametrize("filename", ["projectctl.scope.yaml", "projectctl.parallel.yaml"])
def test_scope_authority_directories_fail_closed(tmp_path: Path, filename: str):
    (tmp_path / filename).mkdir()
    with pytest.raises(ConfigurationError, match="not a regular file"):
        resolve_execution_scope_catalog(tmp_path)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("projectctl.scope.yaml", "schema_kind: projectctl.parallel_scope_catalog\n"),
        ("projectctl.scope.yaml", "tasks: []\n"),
        ("projectctl.scope.yaml", "\u00ff"),
        ("projectctl.parallel.yaml", "schema_kind: projectctl.execution_scope_catalog\n"),
    ],
)
def test_malformed_or_wrong_kind_never_falls_back(
    tmp_path: Path, filename: str, content: str
):
    (tmp_path / filename).write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        resolve_execution_scope_catalog(tmp_path)


def test_generic_catalog_rejects_invalid_scope_and_task_key():
    raw = yaml.safe_load(_raw_scope("projectctl.execution_scope_catalog"))
    raw["tasks"]["task-1"]["writes"] = []
    with pytest.raises(ValidationError):
        ExecutionScopeCatalog.model_validate(raw)

    raw = yaml.safe_load(_raw_scope("projectctl.execution_scope_catalog"))
    raw["tasks"]["task-1"]["inputs"].append({"path": "src/app.py", "kind": "exact"})
    with pytest.raises(ValidationError, match="unique"):
        ExecutionScopeCatalog.model_validate(raw)

    raw = yaml.safe_load(_raw_scope("projectctl.execution_scope_catalog"))
    raw["tasks"]["task-1"]["resources"] = ["parser", "parser"]
    with pytest.raises(ValidationError, match="unique"):
        ExecutionScopeCatalog.model_validate(raw)

    raw = yaml.safe_load(_raw_scope("projectctl.execution_scope_catalog"))
    raw["tasks"]["task-1"]["writes"][0]["path"] = "../outside"
    with pytest.raises(ValidationError):
        ExecutionScopeCatalog.model_validate(raw)

    raw = yaml.safe_load(_raw_scope("projectctl.execution_scope_catalog"))
    raw["tasks"]["task-1"]["task_id"] = "other"
    with pytest.raises(ValidationError, match="does not match task_id"):
        ExecutionScopeCatalog.model_validate(raw)


def test_generic_and_legacy_schemas_remain_public():
    assert (
        PUBLIC_SCHEMAS["execution-scope-catalog.v1.schema.json"]
        is ExecutionScopeCatalog
    )
    assert (
        PUBLIC_SCHEMAS["parallel-scope-catalog.v1.schema.json"]
        is ParallelScopeCatalog
    )
    assert (
        PUBLIC_SCHEMAS["project-config.v9.schema.json"]
        is ProjectConfigV9
    )
    assert PUBLIC_SCHEMAS["project-config.v10.schema.json"] is ProjectConfig


@pytest.mark.parametrize(
    "config_class",
    [
        ProjectConfigV1,
        ProjectConfigV2,
        ProjectConfigV3,
        ProjectConfigV4,
        ProjectConfigV5,
        ProjectConfigV6,
        ProjectConfigV7,
        ProjectConfigV8,
        ProjectConfigV9,
    ],
)
def test_all_historical_configs_upgrade_to_optional_without_rewrite(
    tmp_path: Path, config_class
):
    path = tmp_path / ".projectctl" / "config.yaml"
    path.parent.mkdir()
    legacy = config_class(project=ProjectIdentity(id="demo"))
    before = yaml.safe_dump(legacy.model_dump(mode="json"), sort_keys=False)
    path.write_text(before, encoding="utf-8")
    loaded = load_project_config(tmp_path)
    assert loaded.schema_version == 10
    assert loaded.scope_governance.mode == "optional"
    assert loaded.project.id == "demo"
    assert path.read_text(encoding="utf-8") == before


def test_project_config_v10_explicit_required_and_invalid_policy(tmp_path: Path):
    path = tmp_path / ".projectctl" / "config.yaml"
    path.parent.mkdir()
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        scope_governance={"mode": "required"},
    )
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    assert load_project_config(tmp_path).scope_governance.mode == "required"
    with pytest.raises(ValidationError):
        ExecutionTaskScope(
            task_id="task-1",
            inputs=[{"path": "src/app.py"}],
            writes=[{"path": "src/app.py"}],
            resources=["", "valid"],
        )
    with pytest.raises(ValidationError):
        ProjectConfig(project=ProjectIdentity(id="demo"), scope_governance={"mode": "off"})


def test_catalog_byte_parser_rejects_non_mapping():
    with pytest.raises(ConfigurationError):
        parse_execution_scope_catalog_bytes(b"[]\n")
