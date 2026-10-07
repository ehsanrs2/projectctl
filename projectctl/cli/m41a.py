from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.core.errors import ProjectCtlError
from projectctl.parallel import (
    assess_parallel_safety,
    build_parallel_integration_queue,
    build_parallel_plan,
    integrate_parallel_run,
    recover_parallel_project,
    run_parallel_batch,
)
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.core.enums import WorkerStrategyKind
from projectctl.project.root import find_project_root


EXIT_PARALLEL = 22


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m41a(app: typer.Typer) -> None:
    parallel_app = typer.Typer(
        no_args_is_help=True,
        help="Build and inspect deterministic parallel-planning safety proofs.",
    )
    app.add_typer(parallel_app, name="parallel")

    @parallel_app.command("plan")
    def parallel_plan_command(
        task_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        target_ref: str | None = typer.Option(None, "--target-ref"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            plan = build_parallel_plan(
                root,
                task_id,
                integration_target_ref=target_ref,
            )
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(_json(plan))
            return

        typer.echo(f"Parallel plan: {plan.plan_id}")
        typer.echo(f"Task: {plan.task_id}")
        typer.echo(f"Base: {plan.base_commit}")
        typer.echo(f"Target: {plan.integration_target_ref}")
        typer.echo(f"Scoped tasks: {', '.join(plan.scoped_task_ids)}")
        typer.echo("Inputs:")
        for item in plan.inputs:
            typer.echo(
                f"  {item.scope.kind}: {item.scope.path} -> {item.digest}"
            )
        typer.echo("Writes:")
        for item in plan.writes:
            typer.echo(f"  {item.kind}: {item.path}")
        if plan.resources:
            typer.echo("Resources: " + ", ".join(plan.resources))

    @parallel_app.command("assess")
    def parallel_assess_command(
        left_task_id: str,
        right_task_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        target_ref: str | None = typer.Option(None, "--target-ref"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            left = build_parallel_plan(
                root,
                left_task_id,
                integration_target_ref=target_ref,
            )
            right = build_parallel_plan(
                root,
                right_task_id,
                integration_target_ref=target_ref,
            )
            decision = assess_parallel_safety(
                left,
                right,
                persist_root=root,
            )
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(
                _json(
                    {
                        "left": left.model_dump(mode="json"),
                        "right": right.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    }
                )
            )
            return

        typer.echo(
            "Parallel-safe: " + ("yes" if decision.independent else "no")
        )
        typer.echo(f"Shared target: {decision.shared_target}")
        typer.echo(f"Shared base: {decision.shared_base}")
        typer.echo(
            "Integration reverification required after target advancement: "
            + str(decision.integration_requires_reverification)
        )
        if decision.conflicts:
            typer.echo("Conflicts:")
            for conflict in decision.conflicts:
                typer.echo(f"  {conflict.reason}: {conflict.detail}")

    @parallel_app.command("queue")
    def parallel_queue_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        target_ref: str | None = typer.Option(None, "--target-ref"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            queue = build_parallel_integration_queue(
                root,
                target_ref=target_ref,
                persist=True,
            )
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(_json(queue))
            return

        typer.echo(f"Target: {queue.target_ref}")
        if not queue.entries:
            typer.echo("Integration queue is empty.")
            return
        for item in queue.entries:
            typer.echo(
                f"  {item.position}. {item.run_id} task={item.task_id} "
                f"status={item.status.value} base={item.base_commit[:12]}"
            )

    @parallel_app.command("integrate")
    def parallel_integrate_command(
        run_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            result = integrate_parallel_run(root, run_id)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(
                _json(
                    {
                        "run": result.record.model_dump(mode="json"),
                        "integration": result.manifest.model_dump(mode="json"),
                    }
                )
            )
            return
        typer.echo(f"Run: {result.record.run_id}")
        typer.echo(f"Status: {result.record.status.value}")

    @parallel_app.command("recover")
    def parallel_recover_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            details = recover_parallel_project(root)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(_json({"details": details}))
            return
        if not details:
            typer.echo("No active parallel runs require recovery.")
        for item in details:
            typer.echo(item)

    @parallel_app.command("run")
    def parallel_run_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        max_runs: int = typer.Option(
            2,
            "--max-runs",
            min=2,
            max=8,
            help="Maximum number of same-project active runs in this bounded batch.",
        ),
        strategy: str | None = typer.Option(
            None,
            "--strategy",
            help="Requested worker strategy.",
        ),
        allow_goal_fallback: bool = typer.Option(False, "--allow-goal-fallback"),
        allow_plan_fallback: bool = typer.Option(False, "--allow-plan-fallback"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            requested = WorkerStrategyKind(strategy) if strategy else None
            result = run_parallel_batch(
                root,
                max_parallel_runs=max_runs,
                requested_strategy=requested,
                fallback=StrategyFallbackPolicy(
                    allow_goal_to_plan_then_execute=allow_goal_fallback,
                    allow_plan_to_direct=allow_plan_fallback,
                ),
            )
        except (ProjectCtlError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PARALLEL)

        if json_output:
            typer.echo(_json(result))
            return

        typer.echo(f"Parallel batch max active runs: {result.max_parallel_runs}")
        typer.echo(f"Prepared: {len(result.prepared_run_ids)}")
        typer.echo(f"Completed: {len(result.completed_run_ids)}")
        typer.echo(f"Remaining active: {len(result.remaining_run_ids)}")
        for item in result.details:
            typer.echo(f"  {item}")
