from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from projectctl.context.adoption import (
    adopt_scope_review,
    create_scope_review,
    render_review_diff,
)
from projectctl.context.discovery import discover_context, suggest_scope
from projectctl.core.errors import ProjectCtlError
from projectctl.project.root import find_project_root


EXIT_CONTEXT = 23


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m50(app: typer.Typer) -> None:
    context_app = typer.Typer(
        no_args_is_help=True,
        help=(
            "Build non-authoritative repository/code context evidence and "
            "scope suggestions."
        ),
    )
    app.add_typer(context_app, name="context")

    @context_app.command("discover")
    def context_discover_command(
        task_id: str,
        project: Path = typer.Option(
            Path("."),
            "--project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
        target_ref: str | None = typer.Option(None, "--target-ref"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            report = discover_context(
                root,
                task_id,
                integration_target_ref=target_ref,
                persist=True,
            )
        except (ProjectCtlError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_CONTEXT)

        if json_output:
            typer.echo(_json(report))
            return

        typer.echo(f"Context discovery: {report.discovery_id}")
        typer.echo(f"Project: {report.project_id}")
        typer.echo(f"Task: {report.task_id}")
        typer.echo(f"Base: {report.base_commit[:12]}")
        typer.echo(
            f"Repository files: {report.repository_file_count}; "
            f"Python AST indexed: {report.indexed_python_files}"
        )
        typer.echo(
            "Graphify: "
            + (
                f"enabled digest={report.graphify_digest or '-'}"
                if report.graphify_enabled
                else "disabled"
            )
        )
        typer.echo("Authority: derived suggestion only")
        typer.echo("\nCandidates")
        if not report.candidates:
            typer.echo("  none")
        for candidate in report.candidates:
            typer.echo(
                f"  {candidate.score:>3} {candidate.path} "
                f"roles={','.join(candidate.roles)}"
            )
            for reason in candidate.reasons:
                typer.echo(f"      - {reason}")
        if report.warnings:
            typer.echo("\nWarnings")
            for warning in report.warnings:
                typer.echo(f"  - {warning}")

    @context_app.command("suggest-scope")
    def context_suggest_scope_command(
        task_id: str,
        project: Path = typer.Option(
            Path("."),
            "--project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
        target_ref: str | None = typer.Option(None, "--target-ref"),
        json_output: bool = typer.Option(False, "--json"),
        yaml_output: bool = typer.Option(
            False,
            "--yaml",
            help="Render a review-only task-scope YAML snippet.",
        ),
    ) -> None:
        try:
            root = find_project_root(project)
            suggestion = suggest_scope(
                root,
                task_id,
                integration_target_ref=target_ref,
                persist=True,
            )
        except (ProjectCtlError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_CONTEXT)

        if json_output:
            typer.echo(_json(suggestion))
            return

        if yaml_output:
            snippet = {
                "task_id": suggestion.task_id,
                "inputs": [
                    item.model_dump(mode="json")
                    for item in suggestion.input_scopes
                ],
                "writes": [
                    item.model_dump(mode="json")
                    for item in suggestion.write_scopes
                ],
                "resources": [],
            }
            typer.echo(
                "# REVIEW ONLY: derived suggestion; this output is not authority."
            )
            typer.echo(
                "# ProjectCTL did not modify projectctl.parallel.yaml."
            )
            typer.echo(yaml.safe_dump(snippet, sort_keys=False).rstrip())
            return

        typer.echo(f"Scope suggestion: {suggestion.suggestion_id}")
        typer.echo(f"Task: {suggestion.task_id}")
        typer.echo(f"Base: {suggestion.base_commit[:12]}")
        typer.echo("Authority: false; human review required: true")
        typer.echo("\nSuggested inputs")
        if not suggestion.input_scopes:
            typer.echo("  none")
        for item in suggestion.input_scopes:
            typer.echo(f"  {item.kind}: {item.path}")
        typer.echo("\nSuggested writes")
        if not suggestion.write_scopes:
            typer.echo("  none")
        for item in suggestion.write_scopes:
            typer.echo(f"  {item.kind}: {item.path}")

        typer.echo(
            "\nDeclared scope: "
            + ("present" if suggestion.declared_scope_present else "absent")
        )
        coverage = suggestion.coverage
        groups = [
            (
                "suggested inputs not declared",
                coverage.suggested_inputs_not_declared,
            ),
            (
                "suggested writes not declared",
                coverage.suggested_writes_not_declared,
            ),
            (
                "declared inputs not suggested",
                coverage.declared_inputs_not_suggested,
            ),
            (
                "declared writes not suggested",
                coverage.declared_writes_not_suggested,
            ),
        ]
        for label, values in groups:
            if values:
                typer.echo(f"  {label}: {', '.join(values)}")

        if suggestion.warnings:
            typer.echo("\nWarnings")
            for warning in suggestion.warnings:
                typer.echo(f"  - {warning}")


    @context_app.command("review-scope")
    def context_review_scope_command(
        task_id: str,
        suggestion_id: str = typer.Option(
            ...,
            "--suggestion",
            help="Exact ContextScopeSuggestion id to review.",
        ),
        project: Path = typer.Option(
            Path("."),
            "--project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
        input_path: list[str] | None = typer.Option(
            None,
            "--input",
            help=(
                "Accept only this suggested input path. Repeatable. "
                "Omit to accept all suggested inputs."
            ),
        ),
        write_path: list[str] | None = typer.Option(
            None,
            "--write",
            help=(
                "Accept only this suggested write path. Repeatable. "
                "Omit to accept all suggested writes."
            ),
        ),
        resource: list[str] = typer.Option(
            [],
            "--resource",
            help="Add an explicit human-reviewed exclusive resource key. Repeatable.",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            review = create_scope_review(
                root,
                task_id,
                suggestion_id=suggestion_id,
                input_paths=input_path,
                write_paths=write_path,
                resources=resource,
            )
        except (ProjectCtlError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_CONTEXT)

        if json_output:
            typer.echo(_json(review))
            return

        from projectctl.core.digest import digest

        review_digest = digest(review)
        typer.echo(f"Scope review: {review.review_id}")
        typer.echo(f"Task: {review.task_id}")
        typer.echo(f"Base: {review.base_commit[:12]}")
        typer.echo(f"Review digest: {review_digest}")
        typer.echo("Mutation mode: additive")
        typer.echo("Approval required: exact review digest")
        typer.echo("\nAccepted additions")
        typer.echo(
            "  inputs: "
            + (", ".join(review.added_inputs) if review.added_inputs else "none")
        )
        typer.echo(
            "  writes: "
            + (", ".join(review.added_writes) if review.added_writes else "none")
        )
        typer.echo(
            "  resources: "
            + (
                ", ".join(review.added_resources)
                if review.added_resources
                else "none"
            )
        )
        typer.echo("\nReviewed policy diff")
        diff_text = render_review_diff(review)
        typer.echo(diff_text or "  no byte-level policy change")
        typer.echo("\nTo adopt this exact review:")
        typer.echo(
            "  projectctl context adopt-scope "
            f"{task_id} --review {review.review_id} "
            f"--approve-digest {review_digest}"
        )

    @context_app.command("adopt-scope")
    def context_adopt_scope_command(
        task_id: str,
        review_id: str = typer.Option(
            ...,
            "--review",
            help="Exact ContextScopeReview id to adopt.",
        ),
        approval_digest: str = typer.Option(
            ...,
            "--approve-digest",
            help=(
                "Exact review digest printed by review-scope. "
                "This binds approval to the reviewed bytes."
            ),
        ),
        project: Path = typer.Option(
            Path("."),
            "--project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            receipt = adopt_scope_review(
                root,
                task_id,
                review_id=review_id,
                approval_digest=approval_digest,
            )
        except (ProjectCtlError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_CONTEXT)

        if json_output:
            typer.echo(_json(receipt))
            return

        typer.echo(f"Scope adoption: {receipt.adoption_id}")
        typer.echo(f"Review: {receipt.review_id}")
        typer.echo(f"Task: {receipt.task_id}")
        typer.echo(f"Catalog: {receipt.catalog_path}")
        typer.echo(f"Before: {receipt.catalog_before_digest}")
        typer.echo(f"After: {receipt.catalog_after_digest}")
        typer.echo(f"Scope digest: {receipt.scope_after_digest}")
        typer.echo("Applied: true")
