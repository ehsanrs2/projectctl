from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.application.status import collect_status
from projectctl.core.errors import ConfigurationError, ProjectCtlError, TaskStoreError
from projectctl.project.generated import refresh_generated
from projectctl.project.root import find_project_root
from projectctl.project.state import load_project_state, update_project_state

EXIT_REPOSITORY = 11
EXIT_TASK_STORE = 12


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m05(app: typer.Typer) -> None:
    state_app = typer.Typer(invoke_without_command=True, help="Inspect or update structured project state.")
    app.add_typer(state_app, name="state")

    @state_app.callback()
    def state_command(
        ctx: typer.Context,
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        try:
            root = find_project_root(project)
            state = load_project_state(root, allow_missing=True)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)
        if json_output:
            typer.echo(_json(state))
            return
        typer.echo(f"Project: {state.project_id}")
        typer.echo(f"Current goal: {state.current_goal or 'not set'}")
        if state.active_milestone:
            text = state.active_milestone.id
            if state.active_milestone.title:
                text += f" — {state.active_milestone.title}"
            typer.echo(f"Active milestone: {text}")
            if state.active_milestone.aliases:
                typer.echo("Aliases: " + ", ".join(state.active_milestone.aliases))
        else:
            typer.echo("Active milestone: not set")

    @state_app.command("set")
    def state_set_command(
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        goal: str | None = typer.Option(None, "--goal"),
        milestone: str | None = typer.Option(None, "--milestone"),
        milestone_title: str | None = typer.Option(None, "--milestone-title"),
        alias: list[str] | None = typer.Option(None, "--alias"),
        clear_goal: bool = typer.Option(False, "--clear-goal"),
        clear_milestone: bool = typer.Option(False, "--clear-milestone"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        if clear_goal and goal is not None:
            raise typer.BadParameter("--clear-goal cannot be combined with --goal")
        if clear_milestone and (milestone is not None or milestone_title is not None or alias):
            raise typer.BadParameter(
                "--clear-milestone cannot be combined with milestone options"
            )
        try:
            root = find_project_root(project)
            state = update_project_state(
                root,
                goal=goal,
                milestone_id=milestone,
                milestone_title=milestone_title,
                aliases=alias,
                clear_goal=clear_goal,
                clear_milestone=clear_milestone,
            )
        except ConfigurationError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)
        if json_output:
            typer.echo(_json(state))
        else:
            typer.echo("Project state updated.")
            typer.echo(f"Current goal: {state.current_goal or 'not set'}")
            typer.echo(
                "Active milestone: "
                + (
                    state.active_milestone.id
                    if state.active_milestone is not None
                    else "not set"
                )
            )

    @app.command("status")
    def status_command(
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            bundle = collect_status(root)
        except TaskStoreError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_TASK_STORE)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)

        status = bundle.status
        if json_output:
            typer.echo(_json(status))
            return
        typer.echo(f"Project: {status.project_id}")
        typer.echo(f"Goal: {status.current_goal or 'not set'}")
        if status.active_milestone:
            label = status.active_milestone.id
            if status.active_milestone.title:
                label += f" — {status.active_milestone.title}"
            typer.echo(f"Milestone: {label}")
        else:
            typer.echo("Milestone: not set")
        typer.echo(f"Quota mode: {status.quota_mode.value}" + (" (stale)" if status.quota_stale else ""))
        typer.echo(f"Next task: {status.next_task_id or 'none'}")
        if status.next_model_profile:
            typer.echo(f"Model profile: {status.next_model_profile.value}")
        if status.next_reasoning:
            typer.echo(f"Reasoning: {status.next_reasoning.value}")
        c = status.task_counts
        typer.echo(
            f"Tasks: total={c.total} ready={c.ready} blocked={c.blocked} "
            f"running={c.running} done={c.done} failed={c.failed} decisions={c.needs_decision}"
        )

    @app.command("refresh")
    def refresh_command(
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            bundle = collect_status(root)
            written = refresh_generated(root, bundle)
        except TaskStoreError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_TASK_STORE)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)

        payload = {
            "status": bundle.status.model_dump(mode="json"),
            "source_digest": bundle.source_digest,
            "written": [str(path.relative_to(root)) for path in written],
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo("Generated project dashboards refreshed:")
            for path in written:
                typer.echo(f"  {path.relative_to(root)}")
