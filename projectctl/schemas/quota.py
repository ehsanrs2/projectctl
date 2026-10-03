from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.core.enums import ConfidenceLevel, QuotaSource
from projectctl.schemas.base import ProjectCtlModel, Ratio


class QuotaWindow(ProjectCtlModel):
    remaining_ratio: Ratio | None = None
    reset_at: AwareDatetime | None = None
    source: QuotaSource = QuotaSource.UNKNOWN
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN

    @model_validator(mode="after")
    def validate_known_source_has_value(self):
        if self.source != QuotaSource.UNKNOWN and self.remaining_ratio is None:
            raise ValueError("Known quota source requires remaining_ratio.")
        return self


class QuotaSnapshotV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.quota_snapshot"] = "projectctl.quota_snapshot"
    schema_version: Literal[1] = 1
    provider: str
    account: str
    observed_at: AwareDatetime
    five_hour: QuotaWindow
    weekly: QuotaWindow


class QuotaSnapshot(ProjectCtlModel):
    schema_kind: Literal["projectctl.quota_snapshot"] = "projectctl.quota_snapshot"
    schema_version: Literal[2] = 2
    provider: str
    account: str
    observed_at: AwareDatetime
    five_hour: QuotaWindow
    weekly: QuotaWindow
    ordinary_usage_allowed: bool | None = None
    selected_limit_id: str | None = None
    available_limit_ids: list[str] = Field(default_factory=list)


def parse_quota_snapshot(raw: object) -> QuotaSnapshot:
    if not isinstance(raw, dict):
        raise ValueError("Quota snapshot must be an object.")
    version = raw.get("schema_version", 1)
    if version == 2:
        return QuotaSnapshot.model_validate(raw)
    if version == 1:
        legacy = QuotaSnapshotV1.model_validate(raw)
        return QuotaSnapshot(
            provider=legacy.provider,
            account=legacy.account,
            observed_at=legacy.observed_at,
            five_hour=legacy.five_hour,
            weekly=legacy.weekly,
        )
    raise ValueError(f"Unsupported quota snapshot schema version: {version}")
