from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.core.errors import ProjectCtlError
from projectctl.execution_scope.migration import (
    apply_scope_migration,
    preview_scope_migration,
)
from projectctl.project.root import find_project_root


EXIT_SCOPE_MIGRATION = 24


def register_m52b(app: typer.Typer) -> None:
    scope = typer.Typer(
        no_args_is_help=True,
        help="Inspect and explicitly migrate human-managed execution scope policy.",
    )
    app.add_typer(scope, name="scope")

    @scope.command("migrate")
    def migrate(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        apply: bool = typer.Option(
            False, "--apply", help="Explicitly apply the previewed migration."
        ),
        recover: bool = typer.Option(
            False, "--recover", help="Recover an exact pending migration journal."
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        if apply and recover:
            typer.echo("Use --apply or --recover, not both.", err=True)
            raise typer.Exit(EXIT_SCOPE_MIGRATION)
        try:
            root = find_project_root(project)
            if apply or recover:
                result = apply_scope_migration(root, recover=recover)
            else:
                result = preview_scope_migration(root)
        except (ProjectCtlError, ValueError, OSError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_SCOPE_MIGRATION)

        if json_output:
            if hasattr(result, "__dataclass_fields__"):
                from dataclasses import asdict
                result = asdict(result)
            typer.echo(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
            return
        if apply or recover:
            typer.echo("Migrated execution scope catalog to projectctl.scope.yaml.")
            typer.echo(f"Migration: {result['migration_id']}")
            typer.echo("Inspect and commit the deletion/addition in Git before running workers.")
        else:
            typer.echo("Scope migration preview (read-only):")
            typer.echo(f"  {result.old_path} -> {result.new_path}")
            typer.echo(f"  Source SHA-256: {result.source_sha256}")
            typer.echo(f"  Target SHA-256: {result.target_sha256}")
            typer.echo("  --apply explicitly migrates; --recover resumes a journaled crash.")
            typer.echo("\nProposed projectctl.scope.yaml:")
            typer.echo(result.target_yaml.rstrip())
