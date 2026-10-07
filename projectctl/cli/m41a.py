from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.core.errors import ProjectCtlError
from projectctl.parallel import assess_parallel_safety, build_parallel_plan
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
