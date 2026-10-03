import shutil
from pathlib import Path

from projectctl.core.enums import HealthStatus
from projectctl.core.errors import ConfigurationError, DatabaseVersionError, RepositoryContractError, UnsafePathError
from projectctl.core.paths import resolve_inside_repo
from projectctl.project.bootstrap import projectctl_home
from projectctl.project.loader import load_project_config
from projectctl.project.state import PROJECT_STATE_PATH, load_project_state
from projectctl.project.freshness import generated_freshness
from projectctl.project.root import git_root
from projectctl.schemas.health import HealthCheckResult
from projectctl.storage.sqlite import APPLICATION_ID, DATABASE_VERSION, inspect_db


def check_repository(root: Path) -> HealthCheckResult:
    try:
        detected = git_root(root)
        if detected != root.resolve():
            return HealthCheckResult(
                check_id="repository",
                status=HealthStatus.ERROR,
                summary="Project root does not match Git repository root.",
                details=[f"project={root.resolve()}", f"git={detected}"],
            )
        return HealthCheckResult(check_id="repository", status=HealthStatus.PASS, summary="Git repository root is valid.")
    except RepositoryContractError as exc:
        return HealthCheckResult(check_id="repository", status=HealthStatus.ERROR, summary=str(exc))


def check_config(root: Path) -> HealthCheckResult:
    try:
        config = load_project_config(root)
        for path in [config.paths.project, config.paths.roadmap, config.paths.constraints, config.paths.specs, config.paths.evidence, config.paths.generated]:
            resolve_inside_repo(root, path, must_exist=False)
        for binding in [
            config.knowledge.project_overview, config.knowledge.roadmap, config.knowledge.constraints,
            config.knowledge.architecture, config.knowledge.decisions,
        ]:
            for path in binding.sources:
                resolve_inside_repo(root, path, must_exist=False)
        return HealthCheckResult(check_id="config", status=HealthStatus.PASS, summary="Project configuration is valid.")
    except (ConfigurationError, UnsafePathError) as exc:
        return HealthCheckResult(check_id="config", status=HealthStatus.ERROR, summary=f"Invalid project configuration: {exc}")


def check_required_files(root: Path) -> HealthCheckResult:
    try:
        config = load_project_config(root)
    except ConfigurationError as exc:
        return HealthCheckResult(check_id="required_files", status=HealthStatus.ERROR, summary=str(exc))

    def existing(sources: list[str]) -> list[str]:
        result = []
        for rel in sources:
            path = resolve_inside_repo(root, rel, must_exist=False)
            if path.exists():
                result.append(rel)
        return result

    overview = existing(config.knowledge.project_overview.sources)
    roadmap = existing(config.knowledge.roadmap.sources)
    constraints = existing(config.knowledge.constraints.sources)

    if not overview:
        return HealthCheckResult(
            check_id="required_files", status=HealthStatus.ERROR,
            summary="No project overview knowledge source exists.",
            details=config.knowledge.project_overview.sources,
            remediation=["Bind an existing project overview/README or create one."],
        )

    missing_optional = []
    if not roadmap:
        missing_optional.append("roadmap")
    if not constraints:
        missing_optional.append("constraints")
    if missing_optional:
        return HealthCheckResult(
            check_id="required_files", status=HealthStatus.WARN,
            summary="Core project knowledge is usable, but some recommended bindings are missing.",
            details=missing_optional,
        )

    return HealthCheckResult(check_id="required_files", status=HealthStatus.PASS, summary="Core project knowledge sources exist.")


def _db_check(root: Path, name: str) -> HealthCheckResult:
    path = root / ".projectctl" / name
    try:
        app_id, version = inspect_db(path)
        if app_id != APPLICATION_ID:
            raise DatabaseVersionError(f"Unexpected application_id: {app_id}")
        if version > DATABASE_VERSION:
            raise DatabaseVersionError(f"Database version {version} is newer than supported {DATABASE_VERSION}")
        return HealthCheckResult(check_id=name, status=HealthStatus.PASS, summary=f"{name} is valid (v{version}).")
    except DatabaseVersionError as exc:
        return HealthCheckResult(check_id=name, status=HealthStatus.ERROR, summary=str(exc))


def check_task_store(root: Path) -> HealthCheckResult:
    try:
        provider = load_project_config(root).task_store.provider
    except ConfigurationError as exc:
        return HealthCheckResult(check_id="task_store", status=HealthStatus.ERROR, summary=str(exc))
    if provider == "unresolved":
        return HealthCheckResult(
            check_id="task_store", status=HealthStatus.ERROR,
            summary="Task authority is not configured.",
            remediation=["Choose exactly one task authority before scheduling or importing tasks."],
        )
    if provider == "beads":
        executable = shutil.which("bd")
        if not executable:
            return HealthCheckResult(
                check_id="task_store", status=HealthStatus.ERROR,
                summary="Beads task store is configured but `bd` was not found in PATH.",
                remediation=["Install Beads or configure a different task store."],
            )
        beads_dir = root / ".beads"
        if not beads_dir.exists():
            return HealthCheckResult(
                check_id="task_store", status=HealthStatus.ERROR,
                summary=f"Beads executable found but this repository is not initialized: {beads_dir}",
                remediation=["Run `bd init --quiet` from the repository root."],
            )
        return HealthCheckResult(
            check_id="task_store", status=HealthStatus.PASS,
            summary=f"Beads executable and repository state found: {executable}",
        )
    return HealthCheckResult(check_id="task_store", status=HealthStatus.ERROR, summary=f"Task store provider `{provider}` is configured but its adapter is not implemented yet.")


def check_optional_tools(root: Path) -> list[HealthCheckResult]:
    config = load_project_config(root)
    results = []
    codex = shutil.which("codex")
    results.append(HealthCheckResult(
        check_id="codex", status=HealthStatus.PASS if codex else HealthStatus.WARN,
        summary=f"Codex executable found: {codex}" if codex else "Codex executable not found (not required until M1).",
    ))
    if config.features.spec_kit:
        specify = shutil.which("specify")
        results.append(HealthCheckResult(
            check_id="spec_kit", status=HealthStatus.PASS if specify else HealthStatus.WARN,
            summary=f"Spec Kit executable found: {specify}" if specify else "Spec Kit executable not found.",
        ))
    if config.features.graphify:
        graphify = shutil.which("graphify")
        results.append(HealthCheckResult(
            check_id="graphify", status=HealthStatus.PASS if graphify else HealthStatus.WARN,
            summary=f"Graphify executable found: {graphify}" if graphify else "Graphify is enabled but executable was not found.",
        ))
    return results


def check_global_home() -> HealthCheckResult:
    home = projectctl_home()
    if not home.exists():
        return HealthCheckResult(check_id="global_home", status=HealthStatus.WARN, summary=f"Global home does not exist: {home}")
    return HealthCheckResult(check_id="global_home", status=HealthStatus.PASS, summary=f"Global home: {home}")


def check_project_state(root: Path) -> HealthCheckResult:
    path = root / PROJECT_STATE_PATH
    if not path.exists():
        return HealthCheckResult(
            check_id="project_state",
            status=HealthStatus.WARN,
            summary=f"Structured project state is missing: {PROJECT_STATE_PATH}",
            remediation=["Run projectctl state set to record the current goal and active milestone."],
        )
    try:
        state = load_project_state(root, allow_missing=False)
    except ConfigurationError as exc:
        return HealthCheckResult(
            check_id="project_state",
            status=HealthStatus.ERROR,
            summary=f"Invalid structured project state: {exc}",
        )
    missing = []
    if not state.current_goal:
        missing.append("current_goal")
    if state.active_milestone is None:
        missing.append("active_milestone")
    if missing:
        return HealthCheckResult(
            check_id="project_state",
            status=HealthStatus.WARN,
            summary="Structured project state is valid but incomplete.",
            details=missing,
            remediation=["Use projectctl state set to fill the missing state fields."],
        )
    return HealthCheckResult(
        check_id="project_state",
        status=HealthStatus.PASS,
        summary=f"Structured project state is valid: {PROJECT_STATE_PATH}",
    )


def check_generated_artifacts(root: Path) -> HealthCheckResult:
    try:
        missing, stale, _ = generated_freshness(root)
    except Exception as exc:
        return HealthCheckResult(
            check_id="generated_artifacts",
            status=HealthStatus.WARN,
            summary=f"Could not evaluate generated artifact freshness: {exc}",
            remediation=["Fix task/quota prerequisites, then run projectctl refresh."],
        )
    if missing or stale:
        details = [f"missing: {name}" for name in missing] + [f"stale: {name}" for name in stale]
        return HealthCheckResult(
            check_id="generated_artifacts",
            status=HealthStatus.WARN,
            summary="Generated dashboards are missing or stale.",
            details=details,
            remediation=["Run projectctl refresh."],
        )
    return HealthCheckResult(
        check_id="generated_artifacts",
        status=HealthStatus.PASS,
        summary="Generated dashboards are fresh.",
    )
