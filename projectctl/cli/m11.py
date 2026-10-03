from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.application.execution import abort_prepared_run, prepare_next_run
from projectctl.core.errors import ProjectCtlError
from projectctl.project.root import find_project_root
from projectctl.project.locking import project_lock
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import migrate_project_state_db

EXIT_REPOSITORY = 11
EXIT_RUN = 17


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
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            prepared = prepare_next_run(root, integration_target_ref=target)
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
            typer.echo("No worker has been started.")

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
