from __future__ import annotations

import json

import typer

from projectctl.application.portfolio import (
    collect_portfolio_decision,
    maintain_portfolio_projects,
    run_portfolio_cycle,
    run_portfolio_turn,
)
from projectctl.core.errors import ProjectCtlError


EXIT_PORTFOLIO = 21


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def register_m40b(app: typer.Typer) -> None:
    portfolio_app = typer.Typer(
        no_args_is_help=True,
        help="Inspect and execute account-global cross-project arbitration.",
    )
    app.add_typer(portfolio_app, name="portfolio")

    @portfolio_app.command("next")
    def portfolio_next_command(
        account: str = typer.Option(
            ...,
            "--account",
            help="Quota account whose next project should be selected.",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            decision = collect_portfolio_decision(account)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PORTFOLIO)

        if json_output:
            typer.echo(_json(decision))
            return

        typer.echo(f"Portfolio account: {decision.account_id}")
        typer.echo("=" * 72)
        if decision.account_busy:
            typer.echo(
                "Account busy: "
                f"project_instance={decision.active_project_instance_id} "
                f"run={decision.active_run_id}"
            )
        elif decision.selected_project_instance_id is None:
            typer.echo("No registered project is eligible for the next worker turn.")
        else:
            typer.echo(f"Project: {decision.selected_project_id}")
            typer.echo(f"Instance: {decision.selected_project_instance_id}")
            typer.echo(f"Action: {decision.selected_action}")
            typer.echo(f"Task: {decision.selected_task_id}")
            if decision.selected_run_id:
                typer.echo(f"Run: {decision.selected_run_id}")
            typer.echo(f"Root: {decision.selected_project_root}")

        typer.echo("\nCandidates")
        for candidate in decision.candidates:
            status = "eligible" if candidate.eligible else "excluded"
            reason = (
                f" reasons={','.join(candidate.exclusion_reasons)}"
                if candidate.exclusion_reasons
                else ""
            )
            action = f" action={candidate.action}" if candidate.action else ""
            active = (
                f" active={candidate.active_run_count}/{candidate.max_active_runs}"
            )
            parallel = (
                " parallel-admit"
                if candidate.parallel_admission
                else ""
            )
            queue = (
                f" queue_head={candidate.integration_queue_head_run_id}"
                if candidate.integration_queue_head_run_id
                else ""
            )
            typer.echo(
                f"  {candidate.project_id} [{candidate.project_instance_id}] "
                f"{status}{action}{active}{parallel}{queue}{reason}"
            )

    @portfolio_app.command("maintain")
    def portfolio_maintain_command(
        account: str = typer.Option(..., "--account"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            results, errors = maintain_portfolio_projects(account)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PORTFOLIO)

        if json_output:
            typer.echo(
                _json(
                    {
                        "account_id": account,
                        "projects": [
                            item.model_dump(mode="json")
                            for item in results
                        ],
                        "errors": errors,
                    }
                )
            )
            return

        typer.echo(f"Portfolio maintenance account: {account}")
        for result in results:
            typer.echo(
                f"  {result.project_id}: "
                f"{len(result.steps)} lifecycle step(s)"
            )
        for error in errors:
            typer.echo(f"  error: {error}")

    @portfolio_app.command("cycle")
    def portfolio_cycle_command(
        account: str = typer.Option(..., "--account"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            result = run_portfolio_cycle(account)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PORTFOLIO)

        if json_output:
            typer.echo(_json(result))
            return

        typer.echo(f"Portfolio cycle account: {result.account_id}")
        typer.echo(f"Maintenance projects: {len(result.maintenance)}")
        if result.maintenance_errors:
            typer.echo(
                f"Maintenance errors: {len(result.maintenance_errors)}"
            )
        if result.turn is None:
            if result.decision.account_busy:
                typer.echo(
                    "Worker turn: none (account busy: "
                    f"{result.decision.active_run_id})"
                )
            else:
                typer.echo("Worker turn: none")
        else:
            typer.echo(
                f"Worker turn: {result.turn.project_id} "
                f"{result.turn.action} run={result.turn.run_id}"
            )

    @portfolio_app.command("run")
    def portfolio_run_command(
        account: str = typer.Option(
            ...,
            "--account",
            help="Quota account whose next worker turn should execute.",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            result = run_portfolio_turn(account)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_PORTFOLIO)

        if json_output:
            typer.echo(_json(result))
            return

        typer.echo(f"Portfolio turn: {result.decision.decision_id}")
        typer.echo(f"Project: {result.project_id} [{result.project_instance_id}]")
        typer.echo(f"Action: {result.action}")
        typer.echo(f"Run: {result.run_id}")
        typer.echo(f"Run status: {result.run_status.value}")
