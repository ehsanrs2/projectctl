from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.enums import WorkerStrategyKind
from projectctl.core.errors import ProjectCtlError
from projectctl.project.root import find_project_root
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.workers.codex import CodexCapabilityProbe
from projectctl.workers.strategy import negotiate_strategy

EXIT_REPOSITORY = 11
EXIT_CAPABILITY = 18


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def _probe(provider: str):
    if provider != "codex":
        raise typer.BadParameter(f"Unsupported worker provider: {provider}")
    return CodexCapabilityProbe().probe()


def _support_text(support) -> str:
    return (
        f"runtime={support.runtime.value:11} "
        f"adapter={support.adapter.value:11} "
        f"usable={'yes' if support.usable else 'no'}"
        + (" experimental" if support.experimental else "")
    )


def register_m12a(app: typer.Typer) -> None:
    worker_app = typer.Typer(
        help="Inspect worker capabilities and execution strategy compatibility."
    )
    app.add_typer(worker_app, name="worker")

    @worker_app.command("capabilities")
    def capabilities_command(
        provider: str = typer.Option("codex", "--provider"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        capabilities = _probe(provider)
        if json_output:
            typer.echo(_json(capabilities))
            return

        runtime = capabilities.runtime
        typer.echo(f"Provider: {runtime.provider}")
        typer.echo(f"Probe: {capabilities.probe_kind}")
        typer.echo(f"SDK: {runtime.sdk_name or 'unknown'} {runtime.sdk_version or 'not installed'}")
        typer.echo(
            f"Runtime: {runtime.runtime_name or 'unknown'} "
            f"{runtime.runtime_version or 'not detected'}"
        )
        typer.echo(
            f"Adapter: {runtime.adapter_name or 'unknown'} "
            f"{runtime.adapter_version or 'unknown'}"
        )
        typer.echo("Modes:")
        for mode, support in capabilities.modes.items():
            typer.echo(f"  {mode.value:8} {_support_text(support)}")

        typer.echo("Sandboxes:")
        for sandbox, support in capabilities.permissions.sandboxes.items():
            typer.echo(f"  {sandbox.value:20} {_support_text(support)}")

        typer.echo("Approvals:")
        for approval, support in capabilities.permissions.approvals.items():
            typer.echo(f"  {approval.value:20} {_support_text(support)}")

        for note in capabilities.notes:
            typer.echo(f"Note: {note}")

    @worker_app.command("strategy")
    def strategy_command(
        task_id: str,
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        provider: str = typer.Option("codex", "--provider"),
        requested: str | None = typer.Option(
            None,
            "--requested",
            help="Override requested strategy: direct, plan_then_execute, goal, review.",
        ),
        allow_goal_fallback: bool = typer.Option(False, "--allow-goal-fallback"),
        allow_plan_fallback: bool = typer.Option(False, "--allow-plan-fallback"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            snapshot = capture_task_snapshot(root, state="all")
            task = next((item for item in snapshot.tasks if item.id == task_id), None)
            if task is None:
                typer.echo(f"Unknown task: {task_id}", err=True)
                raise typer.Exit(EXIT_CAPABILITY)
            capabilities = _probe(provider)
            requested_kind = WorkerStrategyKind(requested) if requested else None
            decision = negotiate_strategy(
                task,
                capabilities,
                requested=requested_kind,
                fallback=StrategyFallbackPolicy(
                    allow_goal_to_plan_then_execute=allow_goal_fallback,
                    allow_plan_to_direct=allow_plan_fallback,
                ),
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_CAPABILITY)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)

        if json_output:
            typer.echo(_json(decision))
            if not decision.compatible:
                raise typer.Exit(EXIT_CAPABILITY)
            return

        typer.echo(f"Task: {decision.task_id}")
        typer.echo(f"Requested strategy: {decision.requested.value}")
        typer.echo(
            "Resolved strategy: "
            + (decision.resolved.value if decision.resolved is not None else "none")
        )
        typer.echo(f"Compatible: {'yes' if decision.compatible else 'no'}")
        if decision.unsupported:
            typer.echo("Unsupported: " + ", ".join(decision.unsupported))
        for reason in decision.reasons:
            typer.echo(f"Reason: {reason}")

        if not decision.compatible:
            raise typer.Exit(EXIT_CAPABILITY)
