from pathlib import Path

from projectctl.core.time import utc_now
from projectctl.doctor.checks import (
    _db_check,
    check_code_delivery,
    check_config,
    check_global_home,
    check_optional_tools,
    check_project_state,
    check_quota_provider,
    check_execution_ownership,
    check_generated_artifacts,
    check_repository,
    check_required_files,
    check_task_store,
)
from projectctl.schemas.health import HealthReport


def run_doctor(root: Path) -> HealthReport:
    checks = [
        check_repository(root),
        check_config(root),
        check_required_files(root),
        check_project_state(root),
        _db_check(root, "state.sqlite"),
        _db_check(root, "telemetry.sqlite"),
        check_task_store(root),
        check_execution_ownership(root),
        check_code_delivery(root),
        check_global_home(),
        check_quota_provider(root),
        check_generated_artifacts(root),
    ]
    try:
        checks.extend(check_optional_tools(root))
    except Exception as exc:
        from projectctl.core.enums import HealthStatus
        from projectctl.schemas.health import HealthCheckResult
        checks.append(HealthCheckResult(check_id="optional_tools", status=HealthStatus.WARN, summary=f"Optional tool checks incomplete: {exc}"))
    return HealthReport(generated_at=utc_now(), checks=checks)
