from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from projectctl.application.scheduling import current_quota, scheduling_decision
from projectctl.core.errors import ProjectCtlError, QuotaError, TaskStoreError
from projectctl.project.loader import load_project_config
from projectctl.project.root import find_project_root
from projectctl.quota import ManualQuotaProvider, QuotaManager

EXIT_REPOSITORY = 11
EXIT_TASK_STORE = 12
EXIT_QUOTA = 14


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def _parse_ratio(value: str) -> float:
    raw = value.strip()
    try:
        if raw.endswith("%"):
            ratio = float(raw[:-1]) / 100.0
        else:
            ratio = float(raw)
            if 1.0 < ratio <= 100.0:
                ratio /= 100.0
    except ValueError as exc:
        raise QuotaError(f"Invalid quota ratio: {value!r}") from exc
    if not 0.0 <= ratio <= 1.0:
        raise QuotaError("Quota ratio must be between 0 and 1, or 0% and 100%.")
    return ratio


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise QuotaError(f"Invalid ISO-8601 datetime: {value!r}") from exc
    if parsed.tzinfo is None:
        raise QuotaError("Quota reset time must include a timezone offset or Z.")
    return parsed


def _quota_payload(root: Path):
    config = load_project_config(root)
    snapshot = current_quota(root)
    state = QuotaManager(config.quota).state(snapshot, now=datetime.now().astimezone())
    return {
        "snapshot": snapshot.model_dump(mode="json"),
        "mode": state.mode.value,
        "stale": state.stale,
        "effective": {"five_hour": state.five_hour_effective, "weekly": state.weekly_effective},
    }


def register_m04(app: typer.Typer) -> None:
    quota_app = typer.Typer(invoke_without_command=True, help="Inspect or update global account quota.")
    app.add_typer(quota_app, name="quota")

    @quota_app.callback()
    def quota_command(
        ctx: typer.Context,
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        try:
            root = find_project_root(project)
            payload = _quota_payload(root)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_QUOTA)
        if json_output:
            typer.echo(_json(payload))
            return
        snap = payload["snapshot"]
        typer.echo(f"Quota account: {snap['account']}")
        typer.echo(f"Mode: {payload['mode']}" + (" (stale)" if payload["stale"] else ""))
        for key, label in [("five_hour", "Five-hour"), ("weekly", "Weekly")]:
            window = snap[key]
            remaining = window["remaining_ratio"]
            text = "unknown" if remaining is None else f"{remaining * 100:.1f}%"
            effective = payload["effective"][key]
            effective_text = "unknown" if effective is None else f"{effective * 100:.1f}%"
            typer.echo(f"{label:10} remaining={text:>8} effective={effective_text:>8} source={window['source']}")

    @quota_app.command("set")
    def quota_set_command(
        five_hour: str = typer.Option(..., "--five-hour", help="Remaining five-hour quota, e.g. 0.6 or 60%."),
        weekly: str = typer.Option(..., "--weekly", help="Remaining weekly quota, e.g. 0.4 or 40%."),
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        five_hour_reset: str | None = typer.Option(None, "--five-hour-reset"),
        weekly_reset: str | None = typer.Option(None, "--weekly-reset"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            root = find_project_root(project)
            config = load_project_config(root)
            snapshot = ManualQuotaProvider().set_snapshot(
                account=config.quota.account,
                five_hour=_parse_ratio(five_hour),
                weekly=_parse_ratio(weekly),
                five_hour_reset_at=_parse_optional_datetime(five_hour_reset),
                weekly_reset_at=_parse_optional_datetime(weekly_reset),
            )
            payload = _quota_payload(root)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_QUOTA)
        if json_output:
            typer.echo(_json(payload))
        else:
            typer.echo(f"Stored manual quota for account {snapshot.account}.")
            typer.echo(f"Mode: {payload['mode']}")

    @app.command("next")
    def next_command(
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json", help="Emit SchedulerDecision JSON."),
    ) -> None:
        try:
            root = find_project_root(project)
            decision = scheduling_decision(root)
        except QuotaError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_QUOTA)
        except TaskStoreError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_TASK_STORE)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)
        if json_output:
            typer.echo(_json(decision))
            return
        if decision.selected_task_id is None:
            typer.echo(f"No eligible task. Quota mode: {decision.quota_mode.value}")
            return
        candidate = next(c for c in decision.candidates if c.task_id == decision.selected_task_id)
        typer.echo(f"Next task: {decision.selected_task_id}")
        typer.echo(f"Score: {candidate.score.total if candidate.score else 'n/a'}")
        if candidate.model:
            typer.echo(f"Model profile: {candidate.model.profile.value}")
            typer.echo(f"Reasoning: {candidate.model.reasoning.value}")
        typer.echo(f"Quota mode: {decision.quota_mode.value}")

    @app.command("explain-next")
    def explain_next_command(
        project: Path = typer.Option(Path("."), "--project", exists=True, file_okay=False, resolve_path=True),
        json_output: bool = typer.Option(False, "--json", help="Emit SchedulerDecision JSON."),
    ) -> None:
        try:
            root = find_project_root(project)
            decision = scheduling_decision(root)
        except QuotaError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_QUOTA)
        except TaskStoreError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_TASK_STORE)
        except ProjectCtlError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_REPOSITORY)
        if json_output:
            typer.echo(_json(decision))
            return
        typer.echo(f"Scheduler policy: {decision.policy} v{decision.policy_version}")
        typer.echo(f"Quota mode: {decision.quota_mode.value}")
        typer.echo(f"Selected: {decision.selected_task_id or 'none'}")
        typer.echo("=" * 72)
        for candidate in decision.candidates:
            marker = "*" if candidate.task_id == decision.selected_task_id else " "
            if not candidate.eligibility.eligible:
                reasons = ", ".join(r.value for r in candidate.eligibility.reasons)
                typer.echo(f"{marker} {candidate.task_id:16} EXCLUDED  {reasons}")
                continue
            score = candidate.score
            model = candidate.model
            typer.echo(
                f"{marker} {candidate.task_id:16} score={score.total:>7.3f} "
                f"profile={model.profile.value if model else 'n/a'} reasoning={model.reasoning.value if model else 'n/a'}"
            )
            typer.echo(
                "    + priority={:.3f} milestone={:.3f} unblock={:.3f} info={:.3f} urgency={:.3f} age={:.3f}".format(
                    score.priority, score.milestone_relevance, score.unblock_value,
                    score.information_gain, score.urgency, score.age_bonus,
                )
            )
            typer.echo(
                "    - risk={:.3f} resource={:.3f} quota={:.3f}".format(
                    score.risk_penalty, score.resource_penalty, score.quota_penalty,
                )
            )
