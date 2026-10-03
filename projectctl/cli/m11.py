from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.application.execution import abort_prepared_run, prepare_next_run, start_prepared_run
from projectctl.application.auto import run_auto
from projectctl.application.verification import verify_run
from projectctl.application.integration import integrate_run
from projectctl.application.recovery import recover_run
from projectctl.core.enums import AutoStopReason, WorkerStrategyKind
from projectctl.core.errors import ProjectCtlError
from projectctl.project.root import find_project_root
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.schemas.auto import AutoRunPolicy
from projectctl.project.locking import project_lock
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import migrate_project_state_db

EXIT_REPOSITORY = 11
EXIT_RUN = 17
EXIT_VERIFICATION = 19


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m11(app: typer.Typer) -> None:
    run_app = typer.Typer(help="Prepare and inspect isolated execution runs.")
    app.add_typer(run_app, name="run")

    @app.command("migrate")
    def migrate_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            with project_lock(root, "db-migrate"):
                result = migrate_project_state_db(root / ".projectctl" / "state.sqlite")
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)

        payload = {
            "path": str(result.path),
            "from_version": result.from_version,
            "to_version": result.to_version,
            "applied": result.applied,
            "backup_path": str(result.backup_path) if result.backup_path else None,
        }
        if json_output:
            typer.echo(_json(payload))
        elif result.applied:
            typer.echo(
                f"Migrated project state database v{result.from_version} -> v{result.to_version}."
            )
            typer.echo(f"Backup: {result.backup_path}")
        else:
            typer.echo(
                f"Project state database is already at v{result.to_version}; no migration needed."
            )

    @run_app.command("auto")
    def auto_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        max_tasks: int = typer.Option(
            1,
            "--max-tasks",
            min=1,
            max=100,
            help="Maximum task attempts for this bounded autonomous run.",
        ),
        max_attempts_per_task: int = typer.Option(
            1,
            "--max-attempts-per-task",
            min=1,
            max=10,
        ),
        strategy: str | None = typer.Option(
            None,
            "--strategy",
            help="Requested strategy: direct, plan_then_execute, goal, review.",
        ),
        allow_goal_fallback: bool = typer.Option(False, "--allow-goal-fallback"),
        allow_plan_fallback: bool = typer.Option(False, "--allow-plan-fallback"),
        allow_stale_quota: bool = typer.Option(False, "--allow-stale-quota"),
        allow_critical_quota: bool = typer.Option(False, "--allow-critical-quota"),
        continue_on_project_state_change: bool = typer.Option(
            False, "--continue-on-project-state-change"
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            requested = WorkerStrategyKind(strategy) if strategy else None
            report = run_auto(
                root,
                AutoRunPolicy(
                    max_tasks=max_tasks,
                    max_attempts_per_task=max_attempts_per_task,
                    stop_on_critical_quota=not allow_critical_quota,
                    stop_on_stale_quota=not allow_stale_quota,
                    stop_on_material_project_state_change=not continue_on_project_state_change,
                    requested_strategy=requested,
                    allow_goal_fallback=allow_goal_fallback,
                    allow_plan_fallback=allow_plan_fallback,
                ),
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        if json_output:
            typer.echo(_json(report))
        else:
            typer.echo(f"Auto run: {report.auto_run_id}")
            typer.echo(f"Stop reason: {report.stop_reason.value}")
            typer.echo(f"Attempts: {report.attempted_tasks}")
            typer.echo(f"Completed: {report.completed_tasks}")
            for step in report.steps:
                identity = f" task={step.task_id}" if step.task_id else ""
                run = f" run={step.run_id}" if step.run_id else ""
                typer.echo(
                    f"  [{step.iteration}] {step.action}{identity}{run}"
                    + (
                        f" -> {step.final_status.value}"
                        if step.final_status is not None
                        else ""
                    )
                )

        hard_stops = {
            AutoStopReason.HUMAN_DECISION_REQUIRED,
            AutoStopReason.POLICY_BLOCKED,
            AutoStopReason.RUN_FAILED,
            AutoStopReason.RECOVERY_REQUIRED,
            AutoStopReason.ACTIVE_RUN_PRESENT,
            AutoStopReason.MULTIPLE_ACTIVE_RUNS,
            AutoStopReason.RETRY_BUDGET_EXHAUSTED,
        }
        if report.stop_reason in hard_stops:
            raise typer.Exit(16)

    @run_app.command("prepare")
    def prepare_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        target: str | None = typer.Option(
            None,
            "--target",
            help="Integration target ref. Defaults to the current branch.",
        ),
        strategy: str | None = typer.Option(
            None,
            "--strategy",
            help="Requested strategy: direct, plan_then_execute, goal, review.",
        ),
        allow_goal_fallback: bool = typer.Option(False, "--allow-goal-fallback"),
        allow_plan_fallback: bool = typer.Option(False, "--allow-plan-fallback"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            requested = WorkerStrategyKind(strategy) if strategy else None
            prepared = prepare_next_run(
                root,
                integration_target_ref=target,
                requested_strategy=requested,
                fallback=StrategyFallbackPolicy(
                    allow_goal_to_plan_then_execute=allow_goal_fallback,
                    allow_plan_to_direct=allow_plan_fallback,
                ),
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        payload = {
            "plan": prepared.plan.model_dump(mode="json"),
            "run": prepared.record.model_dump(mode="json"),
            "worktree": {
                "id": prepared.worktree.worktree_id,
                "path": str(prepared.worktree.path),
                "branch": prepared.worktree.branch_name,
                "base_commit": prepared.worktree.base_commit,
            },
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Prepared run: {prepared.record.run_id}")
            typer.echo(f"Task: {prepared.record.task_id}")
            typer.echo(f"Status: {prepared.record.status.value}")
            typer.echo(f"Branch: {prepared.record.branch_name}")
            typer.echo(f"Worktree: {prepared.record.worktree_path}")
            typer.echo(f"Strategy: {prepared.plan.strategy.value}")
            typer.echo("No worker has been started.")

    @run_app.command("start")
    def start_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            started = start_prepared_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        payload = {
            "run": started.record.model_dump(mode="json"),
            "worker_result": started.result.model_dump(mode="json"),
            "context_manifest": started.context.manifest.model_dump(mode="json"),
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Worker finished for run {started.record.run_id}.")
            typer.echo(f"Worker status: {started.result.status.value}")
            typer.echo(f"Run status: {started.record.status.value}")
            if started.record.status.value == "verifying":
                typer.echo("Independent verification has not run yet; M1.3 owns that gate.")

    @run_app.command("verify")
    def verify_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            verified = verify_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        payload = {
            "run": verified.record.model_dump(mode="json"),
            "verification": verified.verification.model_dump(mode="json"),
            "evidence": verified.evidence.model_dump(mode="json"),
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Verification finished for run {verified.record.run_id}.")
            typer.echo(
                f"Overall: {'PASS' if verified.verification.overall_pass else 'FAIL'}"
            )
            typer.echo(f"Run status: {verified.record.status.value}")
            if verified.record.candidate_commit:
                typer.echo(f"Candidate: {verified.record.candidate_commit}")
            if verified.verification.policy_violations:
                typer.echo("Policy violations:")
                for violation in verified.verification.policy_violations:
                    typer.echo(f"  {violation}")

        if not verified.verification.overall_pass:
            raise typer.Exit(EXIT_VERIFICATION)

    @run_app.command("integrate")
    def integrate_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            integrated = integrate_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        payload = {
            "run": integrated.record.model_dump(mode="json"),
            "integration": integrated.manifest.model_dump(mode="json"),
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Integrated run {integrated.record.run_id}.")
            typer.echo(f"Status: {integrated.record.status.value}")
            typer.echo(f"Candidate: {integrated.record.candidate_commit}")
            typer.echo(
                "Worktree cleanup: "
                + ("complete" if integrated.manifest.worktree_cleaned else "pending")
            )

    @run_app.command("recover")
    def recover_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            action = recover_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        if json_output:
            typer.echo(_json(action))
        else:
            typer.echo(f"Recovery: {action.action}")
            typer.echo(
                f"Status: {action.previous_status} -> {action.resolved_status}"
            )
            for detail in action.details:
                typer.echo(f"  {detail}")

    @run_app.command("show")
    def show_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            store = RunStore(root)
            record = store.get(run_id)
            manifest = store.manifest(run_id)
            events = store.events(run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        payload = {
            "run": record.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Run: {record.run_id}")
            typer.echo(f"Task: {record.task_id}")
            typer.echo(f"Status: {record.status.value}")
            typer.echo(f"Base: {record.base_commit}")
            typer.echo(f"Branch: {record.branch_name}")
            typer.echo(f"Worktree: {record.worktree_path}")
            typer.echo(f"Lease owner: {record.lease_owner or 'none'}")
            typer.echo(f"Events: {len(events)}")

    @run_app.command("abort")
    def abort_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            record = abort_prepared_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        if json_output:
            typer.echo(_json(record))
        else:
            typer.echo(f"Aborted run {record.run_id}.")
            typer.echo(f"Status: {record.status.value}")

    @app.command("runs")
    def runs_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        limit: int = typer.Option(100, "--limit", min=1, max=1000),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            records = RunStore(root).list(limit=limit)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_RUN)

        if json_output:
            typer.echo(_json([record.model_dump(mode="json") for record in records]))
            return
        if not records:
            typer.echo("No runs.")
            return
        for record in records:
            typer.echo(
                f"{record.run_id:38} {record.status.value:20} "
                f"{record.task_id:18} {record.branch_name}"
            )
