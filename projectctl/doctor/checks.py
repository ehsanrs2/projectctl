import shutil
from pathlib import Path

from projectctl.core.enums import HealthStatus
from projectctl.core.errors import ConfigurationError, DatabaseVersionError, IntegrationError, ProviderUnavailableError, QuotaError, RepositoryContractError, TaskStoreError, UnsafePathError
from projectctl.core.paths import resolve_inside_repo
from projectctl.git.ref_lease import RemoteRefLease
from projectctl.git.remote import normalize_git_remote_identity
from projectctl.integrations.github import GitHubIssuesClient
from projectctl.integrations.github.repository import parse_github_repository
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.jira.client import JiraCloudClient
from projectctl.integrations.linear.lifecycle import COMPLETED_LABEL, NEEDS_DECISION_LABEL
from projectctl.integrations.delivery import code_delivery_policy, resolve_code_delivery
from projectctl.integrations.execution_ownership import resolve_execution_ownership
from projectctl.project.bootstrap import projectctl_home
from projectctl.project.loader import load_project_config
from projectctl.project.state import PROJECT_STATE_PATH, load_project_state
from projectctl.project.freshness import generated_freshness
from projectctl.project.root import git_root
from projectctl.quota import get_account_quota_provider, resolve_quota_provider
from projectctl.schemas.health import HealthCheckResult
from projectctl.storage.sqlite import (APPLICATION_ID, GLOBAL_STATE_DB_VERSION, PROJECT_STATE_DB_VERSION, TELEMETRY_DB_VERSION, inspect_db)


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
    expected = PROJECT_STATE_DB_VERSION if name == "state.sqlite" else TELEMETRY_DB_VERSION
    try:
        app_id, version = inspect_db(path)
        if app_id != APPLICATION_ID:
            raise DatabaseVersionError(f"Unexpected application_id: {app_id}")
        if version > expected:
            raise DatabaseVersionError(
                f"Database version {version} is newer than supported {expected}"
            )
        if version < expected:
            remediation = ["Run projectctl migrate."] if name == "state.sqlite" else []
            return HealthCheckResult(
                check_id=name,
                status=HealthStatus.ERROR,
                summary=f"{name} requires migration: v{version} -> v{expected}.",
                remediation=remediation,
            )
        return HealthCheckResult(
            check_id=name,
            status=HealthStatus.PASS,
            summary=f"{name} is valid (v{version}).",
        )
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
    if provider == "github":
        executable = shutil.which("gh")
        if not executable:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary="GitHub task store is configured but `gh` was not found in PATH.",
                remediation=["Install GitHub CLI and authenticate it, or configure a different task store."],
            )
        try:
            config = load_project_config(root)
            client = GitHubIssuesClient(
                root,
                repository=config.task_store.repository,
                executable=executable,
            )
            info = client.repository_info()
        except (ProviderUnavailableError, TaskStoreError) as exc:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary=f"GitHub Issues task authority is not readable: {exc}",
                remediation=["Verify `gh auth status`, repository access, and task_store.repository."],
            )
        full_name = str(info.get("full_name") or client.repository)

        return HealthCheckResult(
            check_id="task_store",
            status=HealthStatus.WARN,
            summary=(
                f"GitHub task authority is readable and adapter-complete for {full_name}; "
                "remote write policy is verified only during real claim/publication."
            ),
            details=[
                "Scheduling/status reads are enabled.",
                "Task API readability is independent from code transport/ownership.",
                "Execution ownership and Git transport are checked separately.",
                "M3.0c completion still requires remote publication for GitHub tasks.",
                "Completion/needs-decision mutations are additive ProjectCTL labels and do not overwrite native issue close reasons.",
                "Git write permission and repository rules are proven only by actual claim/publication attempts.",
            ],
        )

    if provider == "linear":
        config = load_project_config(root)
        if not config.task_store.team:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary="Linear task authority is configured without task_store.team.",
                remediation=["Set task_store.team to the Linear team UUID."],
            )
        try:
            client = LinearIssuesClient(
                root,
                team_id=config.task_store.team,
            )
            team = client.team_info()
            client.team_label_ids([COMPLETED_LABEL, NEEDS_DECISION_LABEL])
        except (ProviderUnavailableError, TaskStoreError) as exc:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary=f"Linear task authority is not readable: {exc}",
                remediation=[
                    "Set exactly one of LINEAR_API_KEY or LINEAR_ACCESS_TOKEN, "
                    "verify the configured team UUID, and confirm read access."
                ],
            )
        return HealthCheckResult(
            check_id="task_store",
            status=HealthStatus.WARN,
            summary=(
                f"Linear task authority and lifecycle label namespace are readable for team "
                f"{str(team.get('name') or config.task_store.team)}."
            ),
            details=[
                "Scheduling/status reads include blocker and parent/sub-issue semantics.",
                "Unstarted issues may become READY only when no unresolved blocker is present.",
                "Backlog issues remain PLANNED; started issues are observational RUNNING.",
                "ProjectCTL lifecycle completion/decision markers are additive team-scoped labels.",
                "Native Linear workflow state and human labels are not overwritten.",
                "Provider-native claim/release remain separate from ProjectCTL execution ownership.",
                "Linear label write permission is proven only by an actual lifecycle mutation.",
                "ProjectCTL does not persist Linear credentials.",
            ],
        )

    if provider == "jira":
        config = load_project_config(root)
        if not config.task_store.site or not config.task_store.project:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary="Jira task authority is missing site/project identity.",
                remediation=[
                    "Set task_store.site to <tenant>.atlassian.net and "
                    "task_store.project to the Jira project key."
                ],
            )
        try:
            client = JiraCloudClient(
                root,
                site=config.task_store.site,
                project_key=config.task_store.project,
            )
            project = client.project_info()
            client.list_all(page_size=1)

            ready_policy = {
                item.id: item for item in config.task_store.jira_policy.ready_statuses
            }
            if ready_policy:
                status_catalog = {
                    str(item.get("id") or "").strip(): item
                    for item in client.statuses()
                }
                for status_id, expected in ready_policy.items():
                    observed = status_catalog.get(status_id)
                    if observed is None:
                        raise TaskStoreError(
                            f"Configured Jira READY status {status_id!r} is not visible."
                        )
                    observed_name = str(observed.get("name") or "").strip()
                    category = observed.get("statusCategory")
                    category_key = (
                        str(category.get("key") or "").strip().casefold()
                        if isinstance(category, dict)
                        else str(category or "").strip().casefold()
                    )
                    if observed_name != expected.name:
                        raise TaskStoreError(
                            f"Configured Jira READY status {status_id!r} changed "
                            f"name from {expected.name!r} to {observed_name!r}."
                        )
                    if category_key not in {"new", "to-do", "todo"}:
                        raise TaskStoreError(
                            f"Configured Jira READY status {status_id!r} is no "
                            f"longer in a to-do/new category."
                        )

            link_policy = {
                item.type_id: item for item in config.task_store.jira_policy.link_rules
            }
            if link_policy:
                link_catalog = {
                    str(item.get("id") or "").strip(): item
                    for item in client.issue_link_types()
                }
                for type_id, expected in link_policy.items():
                    observed = link_catalog.get(type_id)
                    if observed is None:
                        raise TaskStoreError(
                            f"Configured Jira link type {type_id!r} is not visible."
                        )
                    actual = (
                        str(observed.get("name") or "").strip(),
                        str(observed.get("inward") or "").strip(),
                        str(observed.get("outward") or "").strip(),
                    )
                    pinned = (
                        expected.name,
                        expected.inward_label,
                        expected.outward_label,
                    )
                    if actual != pinned:
                        raise TaskStoreError(
                            f"Configured Jira link type {type_id!r} metadata changed "
                            "from the pinned ProjectCTL policy."
                        )
        except (ProviderUnavailableError, TaskStoreError) as exc:
            return HealthCheckResult(
                check_id="task_store",
                status=HealthStatus.ERROR,
                summary=f"Jira task authority/eligibility policy is not readable: {exc}",
                remediation=[
                    "Set JIRA_EMAIL and JIRA_API_TOKEN at runtime, verify Browse "
                    "Projects permission, and review task_store.jira_policy."
                ],
            )

        ready_count = len(config.task_store.jira_policy.ready_statuses)
        link_count = len(config.task_store.jira_policy.link_rules)
        return HealthCheckResult(
            check_id="task_store",
            status=HealthStatus.WARN,
            summary=(
                f"Jira Cloud authority is readable for project "
                f"{str(project.get('key') or config.task_store.project)} with "
                f"{ready_count} READY status rule(s) and {link_count} link rule(s)."
            ),
            details=[
                "M3.3b readiness is based on explicitly pinned Jira status ids.",
                "Issue-link semantics are pinned by type id/name/inward/outward labels.",
                "Unknown/custom issue-link semantics fail closed to NEEDS_DECISION.",
                "Parent/sub-task hierarchy remains separate from dependencies.",
                "Lifecycle writes and provider-native claim/release remain unsupported.",
                "Jira credentials are runtime-only and are never persisted by ProjectCTL.",
            ],
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



def check_execution_ownership(root: Path) -> HealthCheckResult:
    try:
        ownership = resolve_execution_ownership(root)
        policy = ownership.policy
    except (ConfigurationError, ProviderUnavailableError, TaskStoreError) as exc:
        return HealthCheckResult(
            check_id="execution_ownership",
            status=HealthStatus.ERROR,
            summary=f"Execution ownership configuration is invalid: {exc}",
        )

    if policy.strategy == "local_lock":
        return HealthCheckResult(
            check_id="execution_ownership",
            status=HealthStatus.WARN,
            summary="Execution ownership is project-local only.",
            details=[
                f"task_provider={policy.task_provider}",
                "Concurrent ProjectCTL processes sharing this project filesystem are serialized.",
                "No cross-machine distributed ownership is claimed.",
            ],
        )

    if policy.strategy == "task_native":
        return HealthCheckResult(
            check_id="execution_ownership",
            status=HealthStatus.PASS,
            summary=f"Execution ownership is task-native for {policy.task_provider}.",
        )

    try:
        assert policy.remote_name is not None
        assert policy.remote_identity is not None
        lease = RemoteRefLease(root, remote_name=policy.remote_name)
        observed_identity = normalize_git_remote_identity(lease.remote_url())
        if observed_identity != policy.remote_identity:
            return HealthCheckResult(
                check_id="execution_ownership",
                status=HealthStatus.ERROR,
                summary="Configured Git remote identity does not match the actual remote.",
                details=[
                    f"configured={policy.remote_identity}",
                    f"observed={observed_identity or 'unknown'}",
                ],
            )
        lease.probe_readable()
    except TaskStoreError as exc:
        return HealthCheckResult(
            check_id="execution_ownership",
            status=HealthStatus.WARN,
            summary=f"Distributed Git ownership transport is not readable: {exc}",
            remediation=[
                "Verify the configured Git remote and authentication. "
                "Write permission is proven only by a real claim attempt."
            ],
        )

    return HealthCheckResult(
        check_id="execution_ownership",
        status=HealthStatus.WARN,
        summary=(
            f"Distributed ownership remote is readable: "
            f"{policy.remote_name} -> {policy.remote_identity}."
        ),
        details=[
            "Claim acquisition uses exact remote Git ref leases.",
            "Git hosting vendor is not part of the ownership contract.",
            "Remote write/rules policy is proven only during a real claim.",
        ],
    )



def check_code_delivery(root: Path) -> HealthCheckResult:
    try:
        policy = code_delivery_policy(root)
    except ConfigurationError as exc:
        return HealthCheckResult(
            check_id="code_delivery",
            status=HealthStatus.ERROR,
            summary=f"Code delivery configuration is invalid: {exc}",
        )

    if policy.mode == "local":
        return HealthCheckResult(
            check_id="code_delivery",
            status=HealthStatus.PASS,
            summary="Code delivery is local-only; no network publication is required.",
            details=[
                f"completion_evidence={policy.completion_evidence}",
            ],
        )

    assert policy.remote_name is not None
    assert policy.remote_identity is not None
    try:
        lease = RemoteRefLease(root, remote_name=policy.remote_name)
        observed_identity = normalize_git_remote_identity(lease.remote_url())
        if observed_identity != policy.remote_identity:
            return HealthCheckResult(
                check_id="code_delivery",
                status=HealthStatus.ERROR,
                summary="Configured delivery remote identity does not match the actual Git remote.",
                details=[
                    f"configured={policy.remote_identity}",
                    f"observed={observed_identity or 'unknown'}",
                ],
            )
        lease.probe_readable()
    except TaskStoreError as exc:
        return HealthCheckResult(
            check_id="code_delivery",
            status=HealthStatus.WARN,
            summary=f"Configured delivery remote is not readable: {exc}",
            remediation=[
                "Verify the configured Git remote and authentication. "
                "ProjectCTL will not infer a different delivery path."
            ],
        )

    if policy.mode == "review_required":
        if not policy.supported or not policy.review_provider:
            return HealthCheckResult(
                check_id="code_delivery",
                status=HealthStatus.ERROR,
                summary=(
                    "Review-required delivery has no built-in adapter for the configured Git host."
                ),
                details=[
                    f"remote={policy.remote_name} -> {policy.remote_identity}",
                    "ProjectCTL will not silently fall back to direct push.",
                ],
            )
        try:
            delivery = resolve_code_delivery(root)
            if delivery.reviewer is None:
                raise ConfigurationError("Review delivery adapter did not resolve.")
        except (ConfigurationError, IntegrationError, ProviderUnavailableError) as exc:
            return HealthCheckResult(
                check_id="code_delivery",
                status=HealthStatus.ERROR,
                summary=f"Review delivery runtime is unavailable: {exc}",
                remediation=[
                    "Authenticate the configured review provider without storing credentials in ProjectCTL."
                ],
            )
        return HealthCheckResult(
            check_id="code_delivery",
            status=HealthStatus.PASS,
            summary=(
                f"Review delivery is ready through the built-in {policy.review_provider} adapter."
            ),
            details=[
                f"remote={policy.remote_name} -> {policy.remote_identity}",
                "ProjectCTL may create/reconcile a PR/MR but never auto-merges it.",
                "Canonical task completion waits for an externally merged exact candidate.",
            ],
        )

    return HealthCheckResult(
        check_id="code_delivery",
        status=HealthStatus.WARN,
        summary=(
            f"Direct Git delivery remote is readable: "
            f"{policy.remote_name} -> {policy.remote_identity}."
        ),
        details=[
            "Publication uses exact-base force-with-lease semantics.",
            "Remote write permission and branch/rules policy are proven only by the real publication attempt.",
        ],
    )


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


def check_quota_provider(root: Path) -> HealthCheckResult:
    try:
        config = load_project_config(root)
        provider_name = get_account_quota_provider(config.quota.account)
    except ConfigurationError as exc:
        return HealthCheckResult(
            check_id="quota_provider",
            status=HealthStatus.ERROR,
            summary=f"Could not resolve quota provider: {exc}",
        )

    if provider_name == "manual":
        return HealthCheckResult(
            check_id="quota_provider",
            status=HealthStatus.PASS,
            summary="Manual account quota provider is configured.",
        )

    try:
        snapshot = resolve_quota_provider(config.quota.account).get_snapshot(config.quota.account)
    except ProviderUnavailableError as exc:
        return HealthCheckResult(
            check_id="quota_provider",
            status=HealthStatus.WARN,
            summary=f"Configured quota provider is temporarily unavailable: {exc}",
            remediation=["Restore Codex App Server availability or switch the account provider to manual."],
        )
    except QuotaError as exc:
        return HealthCheckResult(
            check_id="quota_provider",
            status=HealthStatus.ERROR,
            summary=f"Configured quota provider returned malformed or unsafe data: {exc}",
            remediation=["Update Codex/ProjectCTL or switch to manual quota until the protocol is compatible."],
        )

    details = [
        f"provider={snapshot.provider}",
        f"observed_at={snapshot.observed_at.isoformat()}",
        f"ordinary_usage_allowed={snapshot.ordinary_usage_allowed}",
        f"selected_limit_id={snapshot.selected_limit_id}",
    ]
    return HealthCheckResult(
        check_id="quota_provider",
        status=HealthStatus.PASS,
        summary="Configured quota provider is readable through the supported interface.",
        details=details,
    )
