from pydantic import AwareDatetime, Field

from projectctl.core.enums import HealthStatus
from projectctl.schemas.base import ProjectCtlModel


class HealthCheckResult(ProjectCtlModel):
    check_id: str
    status: HealthStatus
    summary: str
    details: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)


class HealthReport(ProjectCtlModel):
    generated_at: AwareDatetime
    checks: list[HealthCheckResult] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not any(item.status == HealthStatus.ERROR for item in self.checks)
