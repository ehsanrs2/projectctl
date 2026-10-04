import json
from pathlib import Path

import typer

from projectctl import __version__
from projectctl.application.onboarding import build_adoption_plan, inspect_project
from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.errors import (
    DigestMismatchError,
    ProjectCtlError,
    RepositoryContractError,
    TaskImportConflict,
    TaskStoreError,
)
from projectctl.doctor.service import run_doctor
from projectctl.integrations.speckit import SpecKitBeadsImporter
from projectctl.integrations.task_authority import task_authority_capabilities
from projectctl.project.adoption import apply_adoption
from projectctl.project.bootstrap import initialize_project
from projectctl.project.loader import load_project_config
from projectctl.project.root import find_project_root
from projectctl.schema_export import export_json_schemas

app = typer.Typer(no_args_is_help=True, add_completion=False, help="ProjectCTL local control plane")
schema_app = typer.Typer(no_args_is_help=True, help="Schema utilities")
app.add_typer(schema_app, name="schema")

EXIT_REPOSITORY = 11
EXIT_TASK_STORE = 12
EXIT_IMPORT = 13
EXIT_INTERACTION_REQUIRED = 16


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def _project_root(project: Path) -> Path:
    return find_project_root(project)


def _show_inspection(inspection) -> None:
    typer.echo(f"Project classification: {inspection.classification} ({inspection.confidence})")
    if inspection.assets:
        typer.echo("\nExisting assets")
        typer.echo("-" * 56)
        for asset in inspection.assets:
            suffix = f" [{asset.role}]" if asset.role else ""
            typer.echo(f"  {asset.path}{suffix}")
    if inspection.conflicts:
        typer.echo("\nCONFLICTS")
        for conflict in inspection.conflicts:
            typer.echo(f"  {conflict}")
    if inspection.dirty:
        typer.echo("\nWARNING: working tree contains uncommitted changes.")


def _show_plan(plan) -> None:
    typer.echo("\nADOPTION PLAN")
    typer.echo("=" * 56)
    if plan.preserve:
        typer.echo("PRESERVE")
        for item in plan.preserve:
            typer.echo(f"  {item}")
    if plan.knowledge_bindings:
        typer.echo("\nBIND")
        for binding in plan.knowledge_bindings:
            typer.echo(f"  {binding.role}: {', '.join(binding.sources)}")
    typer.echo("\nCREATE")
    for item in plan.create:
        typer.echo(f"  {item}")
    typer.echo(f"\nTask store: {plan.task_store_provider or 'unresolved'}")
    if plan.task_store_repository:
        typer.echo(f"Task repository: {plan.task_store_repository}")
    if plan.unresolved_decisions:
        typer.echo("\nNEEDS DECISION")
        for item in plan.unresolved_decisions:
            typer.echo(f"  {item}")


def _prompt_task_store(inspection) -> str:
    typer.echo("\nTask authority")
    typer.echo("-" * 56)
    if "github" in inspection.detected_task_systems:
        typer.echo("  [1] Use existing GitHub Issues task system")
        typer.echo("  [2] Introduce local Beads")
        typer.echo("  [3] Configure later")
        choice = typer.prompt("Choose", default="1")
        return {"1": "github", "2": "beads", "3": "unresolved"}.get(choice, "github")
    typer.echo("  [1] Use local Beads")
    typer.echo("  [2] Configure later")
    choice = typer.prompt("Choose", default="1")
    return {"1": "beads", "2": "unresolved"}.get(choice, "beads")


def _validate_task_store_choice(value: str | None) -> str | None:
    if value is None:
        return None
    allowed = {"beads", "github", "unresolved"}
    if value not in allowed:
        raise RepositoryContractError(
            f"Unsupported onboarding task store `{value}`. Choose one of: {', '.join(sorted(allowed))}."
        )
    return value


def _interaction_payload(status: str, *, inspection=None, plan=None, reason: str | None = None) -> dict:
    payload = {"status": status}
    if reason:
        payload["reason"] = reason
    if inspection is not None:
        payload["inspection"] = inspection.model_dump(mode="json")
    if plan is not None:
        payload["plan"] = plan.model_dump(mode="json")
    return payload


@app.command("version")
def version() -> None:
    typer.echo(__version__)


@app.command("inspect")
def inspect_command(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    try:
        inspection = inspect_project(path)
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REPOSITORY)
    if json_output:
        typer.echo(_json(inspection))
    else:
        _show_inspection(inspection)


@app.command("init")
def init_command(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Never prompt for input."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe, reversible onboarding changes."),
    task_store: str | None = typer.Option(None, "--task-store", help="Task authority for brownfield adoption."),
    task_store_repository: str | None = typer.Option(
        None,
        "--task-store-repository",
        help="Provider repository identity, e.g. owner/repo for GitHub Issues.",
    ),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help="Allow adoption with uncommitted changes."),
) -> None:
    try:
        inspection = inspect_project(path)

        if inspection.classification == "managed_invalid":
            raise RepositoryContractError(
                "ProjectCTL state already exists but is invalid. Run `projectctl doctor`; no changes were made."
            )

        if inspection.classification == "managed_valid":
            payload = {"status": "already_managed", "project_root": inspection.project_root}
            if json_output:
                typer.echo(_json(payload))
            else:
                typer.echo(f"ProjectCTL is already initialized at {inspection.project_root}")
            return

        if inspection.classification == "new":
            result = initialize_project(path)
            payload = {
                "status": "initialized",
                "mode": "greenfield",
                "project_root": str(result.project_root),
                "created": result.created,
                "preserved": result.preserved,
            }
            if json_output:
                typer.echo(_json(payload))
            else:
                typer.echo(f"Initialized ProjectCTL at {result.project_root}")
                for item in result.created:
                    typer.echo(f"  created   {item}")
                for item in result.preserved:
                    typer.echo(f"  preserved {item}")
            return

        # Brownfield onboarding.
        interactive = not non_interactive and not json_output
        if interactive:
            typer.echo("Existing project detected.\n")
            _show_inspection(inspection)
            typer.echo("\nNo existing project or agent configuration will be modified.")
            if not typer.confirm("Prepare a safe adoption plan?", default=True):
                typer.echo("No changes were made.")
                return

        selected_store = _validate_task_store_choice(task_store)
        if selected_store is None and len(inspection.detected_task_systems) == 1:
            selected_store = inspection.detected_task_systems[0]
        if selected_store is None and interactive:
            selected_store = _prompt_task_store(inspection)

        plan = build_adoption_plan(
            path,
            task_store_provider=selected_store,
            task_store_repository=task_store_repository,
        )

        if json_output or non_interactive:
            if plan.unresolved_decisions or not yes or (plan.dirty and not allow_dirty):
                reason = "human approval required"
                if plan.unresolved_decisions:
                    reason = "unresolved decisions: " + ", ".join(plan.unresolved_decisions)
                elif plan.dirty and not allow_dirty:
                    reason = "working tree is dirty"
                typer.echo(_json(_interaction_payload("interaction_required", inspection=inspection, plan=plan, reason=reason)))
                raise typer.Exit(EXIT_INTERACTION_REQUIRED)
        else:
            _show_plan(plan)
            if plan.dirty and not allow_dirty:
                typer.echo("\nThe working tree is dirty. Inspection is safe, but applying is discouraged.")
                if not typer.confirm("Apply anyway?", default=False):
                    typer.echo("Adoption plan was not applied.")
                    return
                allow_dirty = True
            if not yes and not typer.confirm("Apply this adoption plan?", default=False):
                typer.echo("Adoption plan was not applied.")
                return

        result = apply_adoption(plan, allow_dirty=allow_dirty)
        payload = {
            "status": "initialized",
            "mode": "brownfield",
            "project_root": str(result.project_root),
            "created": result.created,
            "preserved": result.preserved,
            "unresolved_decisions": result.unresolved_decisions,
        }
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Adopted existing project at {result.project_root}")
            for item in result.created:
                typer.echo(f"  created   {item}")
            typer.echo("Existing files were preserved.")
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REPOSITORY)


@app.command("adopt")
def adopt_command(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the adoption plan without making changes."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Never prompt for input."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve safe adoption changes."),
    task_store: str | None = typer.Option(None, "--task-store"),
    task_store_repository: str | None = typer.Option(
        None,
        "--task-store-repository",
        help="Provider repository identity, e.g. owner/repo for GitHub Issues.",
    ),
    allow_dirty: bool = typer.Option(False, "--allow-dirty"),
) -> None:
    try:
        inspection = inspect_project(path)
        interactive = not non_interactive and not json_output
        selected_store = _validate_task_store_choice(task_store)
        if selected_store is None and len(inspection.detected_task_systems) == 1:
            selected_store = inspection.detected_task_systems[0]
        if selected_store is None and interactive and not dry_run:
            selected_store = _prompt_task_store(inspection)
        plan = build_adoption_plan(
            path,
            task_store_provider=selected_store,
            task_store_repository=task_store_repository,
        )

        if dry_run:
            if json_output:
                typer.echo(_json(plan))
            else:
                _show_plan(plan)
            return

        if plan.unresolved_decisions:
            if json_output or non_interactive:
                typer.echo(_json(_interaction_payload("interaction_required", inspection=inspection, plan=plan, reason="unresolved decisions")))
                raise typer.Exit(EXIT_INTERACTION_REQUIRED)
            selected_store = _prompt_task_store(inspection)
            plan = build_adoption_plan(
                path,
                task_store_provider=selected_store,
                task_store_repository=task_store_repository,
            )

        if (json_output or non_interactive) and (not yes or (plan.dirty and not allow_dirty)):
            reason = "working tree is dirty" if plan.dirty and not allow_dirty else "human approval required"
            typer.echo(_json(_interaction_payload("interaction_required", inspection=inspection, plan=plan, reason=reason)))
            raise typer.Exit(EXIT_INTERACTION_REQUIRED)

        if interactive:
            _show_plan(plan)
            if plan.dirty and not allow_dirty:
                if not typer.confirm("Working tree is dirty. Apply anyway?", default=False):
                    typer.echo("Adoption plan was not applied.")
                    return
                allow_dirty = True
            if not yes and not typer.confirm("Apply this adoption plan?", default=False):
                typer.echo("Adoption plan was not applied.")
                return

        result = apply_adoption(plan, allow_dirty=allow_dirty)
        if json_output:
            typer.echo(_json({"status": "adopted", "created": result.created, "preserved": result.preserved}))
        else:
            typer.echo(f"Adopted existing project at {result.project_root}")
    except typer.Exit:
        raise
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REPOSITORY)


@app.command("doctor")
def doctor_command(
    project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    try:
        root = _project_root(project)
        report = run_doctor(root)
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REPOSITORY)

    if json_output:
        typer.echo(_json(report))
    else:
        typer.echo("ProjectCTL Doctor")
        typer.echo("=" * 56)
        for check in report.checks:
            typer.echo(f"{check.status.value.upper():5} {check.check_id:20} {check.summary}")
            for detail in check.details:
                typer.echo(f"      {detail}")
            for remedy in check.remediation:
                typer.echo(f"      remedy: {remedy}")
        typer.echo("=" * 56)
        typer.echo("Project is ready." if report.healthy else "Project is NOT ready.")

    if not report.healthy:
        raise typer.Exit(EXIT_REPOSITORY)


@app.command("task-authority")
def task_authority_command(
    project: Path = typer.Option(
        Path("."),
        "--project",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit TaskAuthorityCapabilities JSON.",
    ),
) -> None:
    try:
        root = _project_root(project)
        capabilities = task_authority_capabilities(root)
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_TASK_STORE)

    if json_output:
        typer.echo(_json(capabilities))
        return

    typer.echo(f"Task authority: {capabilities.provider}")
    typer.echo("=" * 56)
    for name in [
        "read",
        "claim",
        "release",
        "block_for_decision",
        "complete",
    ]:
        typer.echo(f"{name:20} {getattr(capabilities, name).value}")
    for note in capabilities.notes:
        typer.echo(f"note: {note}")


@app.command("tasks")
def tasks_command(
    project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
    state: str = typer.Option("all", "--state", help="Task view: all, ready, or blocked."),
    json_output: bool = typer.Option(False, "--json", help="Emit TaskSnapshot JSON."),
) -> None:
    try:
        root = _project_root(project)
        snapshot = capture_task_snapshot(root, state=state)
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_TASK_STORE)

    if json_output:
        typer.echo(_json(snapshot))
        return

    typer.echo(f"Tasks ({state}) — {snapshot.provider}")
    typer.echo("=" * 72)
    if not snapshot.tasks:
        typer.echo("No tasks found.")
        return
    for task in snapshot.tasks:
        typer.echo(f"{task.id:16} {task.status.value:10} P{task.priority:<2} {task.type.value:12} {task.title}")


@app.command("import-tasks")
def import_tasks_command(
    source: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False),
    project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without mutating Beads."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    try:
        root = _project_root(project)
        provider = load_project_config(root).task_store.provider
        if provider != "beads":
            raise TaskStoreError(
                "Spec Kit import currently targets Beads only. "
                f"Configured task authority is {provider!r}; refusing to create a parallel tracker."
            )
        importer = SpecKitBeadsImporter(root)
        plan = importer.preview(str(source))
        result = plan if dry_run else importer.apply(plan)
    except (TaskImportConflict, DigestMismatchError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_IMPORT)
    except TaskStoreError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_TASK_STORE)
    except ProjectCtlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REPOSITORY)

    if json_output:
        typer.echo(_json(result))
        return

    label = "Import preview" if dry_run else "Import applied"
    typer.echo(f"{label}: {result.source_path}")
    typer.echo("=" * 72)
    for item in result.items:
        target = f" -> {item.target_id}" if item.target_id else ""
        typer.echo(f"{item.action.value.upper():9} {item.source_id}{target}")
        if item.reason:
            typer.echo(f"           {item.reason}")


@schema_app.command("export")
def schema_export_command(
    destination: Path = typer.Option(Path("schemas/generated"), "--destination", file_okay=False),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    written = export_json_schemas(destination.resolve())
    if json_output:
        typer.echo(_json({"written": [str(p) for p in written]}))
    else:
        for path in written:
            typer.echo(str(path))


def main() -> None:
    app()
