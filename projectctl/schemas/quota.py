from typing import Literal

from pydantic import AwareDatetime, model_validator

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


class QuotaSnapshot(ProjectCtlModel):
    schema_kind: Literal["projectctl.quota_snapshot"] = "projectctl.quota_snapshot"
    schema_version: Literal[1] = 1
    provider: str
    account: str
    observed_at: AwareDatetime
    five_hour: QuotaWindow
    weekly: QuotaWindow
