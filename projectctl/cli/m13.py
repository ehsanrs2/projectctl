from __future__ import annotations

import json
from pathlib import Path

import typer

from projectctl.core.errors import ProjectCtlError
from projectctl.project.root import find_project_root
from projectctl.verification.profile import resolve_verification_profile

EXIT_VERIFICATION = 19


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m13(app: typer.Typer) -> None:
    verification_app = typer.Typer(
        help="Inspect deterministic verification policy and profiles."
    )
    app.add_typer(verification_app, name="verification")

    @verification_app.command("profile")
    def profile_command(
        project: Path = typer.Option(
            Path("."), "--project", exists=True, file_okay=False, resolve_path=True
        ),
        profile: str = typer.Option("default", "--profile"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            resolved = resolve_verification_profile(root, profile)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_VERIFICATION)

        payload = {
            "source": resolved.source,
            "profile_digest": resolved.profile_digest,
            "profile": resolved.profile.model_dump(mode="json"),
        }
        if json_output:
            typer.echo(_json(payload))
            return

        typer.echo(f"Profile: {resolved.profile.id}")
        typer.echo(f"Source: {resolved.source}")
        typer.echo(f"Digest: {resolved.profile_digest}")
        typer.echo("Commands:")
        for command in resolved.profile.commands:
            marker = "required" if command.required else "optional"
            typer.echo(
                f"  {command.id}: {command.argv!r} "
                f"(timeout={command.timeout_seconds}s, {marker})"
            )
