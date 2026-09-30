from datetime import datetime, timezone
import math

import pytest
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.task import NormalizedTask, TaskSource
from projectctl.core.enums import QuotaSource, TaskStatus


def test_project_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({
            "schema_kind": "projectctl.project_config",
            "schema_version": 1,
            "project": {"id": "demo"},
            "typo": True,
        })


def test_nan_rejected():
    cfg = ProjectConfig(project=ProjectIdentity(id="demo"))
    data = cfg.model_dump()
    data["scheduler"]["weights"]["priority"] = math.nan
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_mutable_defaults_are_independent():
    a = NormalizedTask(id="a", title="A", source=TaskSource(provider="test", external_id="a"), status=TaskStatus.READY)
    b = NormalizedTask(id="b", title="B", source=TaskSource(provider="test", external_id="b"), status=TaskStatus.READY)
    a.tags.append("x")
    assert b.tags == []


def test_known_quota_source_requires_value():
    with pytest.raises(ValidationError):
        QuotaWindow(source=QuotaSource.MANUAL)


def test_aware_datetime_required():
    with pytest.raises(ValidationError):
        QuotaSnapshot(
            provider="openai", account="x", observed_at=datetime(2026, 1, 1),
            five_hour=QuotaWindow(), weekly=QuotaWindow(),
        )


def test_digest_is_stable():
    a = ProjectConfig(project=ProjectIdentity(id="demo"))
    b = ProjectConfig(project=ProjectIdentity(id="demo"))
    assert digest(a) == digest(b)
