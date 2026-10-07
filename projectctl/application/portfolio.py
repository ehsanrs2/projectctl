from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from projectctl.application.turns import (
    advance_non_worker_phases,
    collect_project_turn_envelope,
    execute_project_turn,
)
from projectctl.core.digest import digest
from projectctl.core.errors import PortfolioError, ProjectCtlError
from projectctl.core.time import utc_now
from projectctl.integrations.execution_ownership import require_project_execution_ready
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.project.loader import load_project_config
from projectctl.project.root import git_root
from projectctl.quota.admission import AccountAdmissionStore, project_instance_id
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.schemas.portfolio import (
    PortfolioCandidate,
    PortfolioCycleResult,
    PortfolioDecision,
    PortfolioTurnResult,
)
from projectctl.storage.sqlite import connect_db


_ACTION_RANK = {
    "resume_run": 0,
    "start_run": 1,
    "admit_task": 2,
}


@dataclass(frozen=True)
class ProjectRegistration:
    project_instance_id: str
    project_id: str
    project_root: Path
    registered_at: datetime
    last_seen_at: datetime


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise PortfolioError("Project registry timestamps must be timezone-aware.")
    return parsed


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-portfolio-",
        suffix=".json",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _registrations(home: Path) -> list[ProjectRegistration]:
    _global_init(home)
    conn = connect_db(home / "state.sqlite", telemetry=False)
    try:
        rows = conn.execute(
            """
            SELECT project_instance_id, project_id, project_root,
                   registered_at, last_seen_at
            FROM project_registry
            ORDER BY project_instance_id
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        ProjectRegistration(
            project_instance_id=str(row["project_instance_id"]),
            project_id=str(row["project_id"]),
            project_root=Path(str(row["project_root"])).expanduser().resolve(),
            registered_at=_parse_time(str(row["registered_at"])),
            last_seen_at=_parse_time(str(row["last_seen_at"])),
        )
        for row in rows
    ]


def _touch_registration(
    home: Path,
    registration: ProjectRegistration,
    *,
    observed_at: datetime,
) -> None:
    conn = connect_db(home / "state.sqlite", telemetry=False)
    try:
        conn.execute(
            """
            UPDATE project_registry
            SET last_seen_at=?
            WHERE project_instance_id=? AND project_id=? AND project_root=?
            """,
            (
                observed_at.isoformat(),
                registration.project_instance_id,
                registration.project_id,
                str(registration.project_root),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _base_candidate(
    registration: ProjectRegistration,
    *,
    observed_at: datetime,
    last_admitted_at: datetime | None,
) -> PortfolioCandidate:
    return PortfolioCandidate(
        project_instance_id=registration.project_instance_id,
        project_id=registration.project_id,
        project_root=str(registration.project_root),
        registered_at=registration.registered_at,
        last_seen_at=registration.last_seen_at,
        observed_at=observed_at,
        last_admitted_at=last_admitted_at,
    )


def _excluded(
    candidate: PortfolioCandidate,
    reason: str,
    detail: str | None = None,
) -> PortfolioCandidate:
    reasons = [*candidate.exclusion_reasons, reason]
    details = [*candidate.details]
    if detail:
        details.append(detail)
    return candidate.model_copy(
        update={
            "eligible": False,
            "action": None,
            "turn": None,
            "exclusion_reasons": reasons,
            "details": details,
        }
    )


def _inspect_registration(
    registration: ProjectRegistration,
    *,
    account_id: str,
    now: datetime,
    home: Path,
    last_admitted_at: datetime | None,
) -> PortfolioCandidate:
    candidate = _base_candidate(
        registration,
        observed_at=now,
        last_admitted_at=last_admitted_at,
    )
    root = registration.project_root

    try:
        if not root.exists() or not root.is_dir():
            return _excluded(candidate, "project_root_missing")
        if git_root(root) != root:
            return _excluded(candidate, "repository_root_mismatch")

        observed_instance = project_instance_id(root)
        if observed_instance != registration.project_instance_id:
            return _excluded(
                candidate,
                "project_instance_mismatch",
                f"registered={registration.project_instance_id} observed={observed_instance}",
            )

        config = load_project_config(root)
        candidate = candidate.model_copy(
            update={"account_id": config.quota.account}
        )
        if config.project.id != registration.project_id:
            return _excluded(
                candidate,
                "project_id_mismatch",
                f"registered={registration.project_id} observed={config.project.id}",
            )

        _touch_registration(home, registration, observed_at=now)

        if config.quota.account != account_id:
            return _excluded(candidate, "different_quota_account")

        require_project_execution_ready(root)
        turn = collect_project_turn_envelope(root, now=now)

        candidate = candidate.model_copy(
            update={
                "account_id": turn.account_id,
                "eligible": turn.eligible,
                "action": turn.action,
                "run_id": turn.run_id,
                "run_status": turn.run_status,
                "selected_task_id": turn.task_id,
                "project_state_digest": turn.project_state_digest,
                "task_snapshot_digest": turn.task_snapshot_digest,
                "quota_snapshot_digest": turn.quota_snapshot_digest,
                "quota_mode": turn.quota_mode,
                "quota_stale": turn.quota_stale,
                "resource_class": turn.resource_class,
                "active_run_ids": turn.active_run_ids,
                "active_run_count": turn.active_run_count,
                "max_active_runs": turn.max_active_runs,
                "parallel_admission": turn.parallel_admission,
                "non_worker_run_ids": turn.non_worker_run_ids,
                "integration_queue_head_run_id": (
                    turn.integration_queue_head_run_id
                ),
                "turn": turn,
                "exclusion_reasons": turn.exclusion_reasons,
                "details": turn.details,
            }
        )
        return candidate
    except ProjectCtlError as exc:
        return _excluded(candidate, "project_unhealthy", str(exc))
    except Exception as exc:
        return _excluded(
            candidate,
            "inspection_error",
            f"{type(exc).__name__}: {exc}",
        )


def _candidate_rank(candidate: PortfolioCandidate):
    assert candidate.eligible and candidate.action is not None
    last = candidate.last_admitted_at
    return (
        _ACTION_RANK[candidate.action],
        last is not None,
        last.timestamp() if last is not None else 0.0,
        candidate.registered_at.timestamp(),
        candidate.project_instance_id,
    )


def collect_portfolio_decision(
    account_id: str,
    *,
    now: datetime | None = None,
    home: Path | None = None,
    persist: bool = True,
) -> PortfolioDecision:
    if not account_id.strip():
        raise PortfolioError(
            "Portfolio arbitration requires a non-empty quota account id."
        )

    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Portfolio evaluation time must be timezone-aware.")

    account_id = account_id.strip()
    home = (home or projectctl_home()).resolve()
    registrations = _registrations(home)
    registry_payload = [
        {
            "project_instance_id": item.project_instance_id,
            "project_id": item.project_id,
            "project_root": str(item.project_root),
            "registered_at": item.registered_at.isoformat(),
        }
        for item in registrations
    ]

    admissions = AccountAdmissionStore(home, clock=lambda: now)
    history = admissions.last_acquired_at_by_project(account_id)
    active_admission = admissions.get(account_id)
    account_busy = (
        active_admission is not None and active_admission.expires_at > now
    )

    candidates = [
        _inspect_registration(
            registration,
            account_id=account_id,
            now=now,
            home=home,
            last_admitted_at=history.get(registration.project_instance_id),
        )
        for registration in registrations
    ]
    eligible = sorted(
        (candidate for candidate in candidates if candidate.eligible),
        key=_candidate_rank,
    )

    selected = None if account_busy or not eligible else eligible[0]
    decision = PortfolioDecision(
        decision_id=f"portfolio-{uuid.uuid4().hex}",
        evaluated_at=now,
        account_id=account_id,
        registry_digest=digest(registry_payload),
        account_busy=account_busy,
        active_project_instance_id=(
            active_admission.project_instance_id
            if account_busy and active_admission is not None
            else None
        ),
        active_run_id=(
            active_admission.run_id
            if account_busy and active_admission is not None
            else None
        ),
        selected_project_instance_id=(
            selected.project_instance_id if selected is not None else None
        ),
        selected_project_id=(
            selected.project_id if selected is not None else None
        ),
        selected_project_root=(
            selected.project_root if selected is not None else None
        ),
        selected_action=selected.action if selected is not None else None,
        selected_run_id=selected.run_id if selected is not None else None,
        selected_task_id=(
            selected.selected_task_id if selected is not None else None
        ),
        candidates=candidates,
    )

    if persist:
        _atomic_json(
            home
            / "portfolio"
            / "decisions"
            / f"{decision.decision_id}.json",
            decision,
        )
    return decision


def _selected_candidate(decision: PortfolioDecision) -> PortfolioCandidate:
    if decision.account_busy:
        raise PortfolioError(
            f"Quota account {decision.account_id!r} already has an active "
            f"worker-turn admission for run {decision.active_run_id}."
        )
    if decision.selected_project_instance_id is None:
        raise PortfolioError(
            f"No registered project is eligible for the next worker turn on "
            f"account {decision.account_id!r}."
        )
    candidate = next(
        (
            item
            for item in decision.candidates
            if item.project_instance_id
            == decision.selected_project_instance_id
        ),
        None,
    )
    if candidate is None or candidate.turn is None or candidate.action is None:
        raise PortfolioError("Selected portfolio candidate is incomplete.")
    return candidate


def _execute_selected(
    decision: PortfolioDecision,
    candidate: PortfolioCandidate,
    *,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> PortfolioTurnResult:
    root = Path(candidate.project_root).resolve()
    project_turn = execute_project_turn(
        root,
        candidate.turn,
        requested_strategy=requested_strategy,
        fallback=fallback,
    )
    return PortfolioTurnResult(
        decision=decision,
        project_instance_id=candidate.project_instance_id,
        project_id=candidate.project_id,
        project_root=candidate.project_root,
        action=candidate.action,
        run_id=project_turn.run_id,
        run_status=project_turn.run_status,
        project_turn=project_turn,
    )


def run_portfolio_turn(
    account_id: str,
    *,
    now: datetime | None = None,
    home: Path | None = None,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> PortfolioTurnResult:
    decision = collect_portfolio_decision(
        account_id,
        now=now,
        home=home,
        persist=True,
    )
    candidate = _selected_candidate(decision)
    return _execute_selected(
        decision,
        candidate,
        requested_strategy=requested_strategy,
        fallback=fallback,
    )


def request_fair_project_turn(
    project_root: Path,
    *,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
    now: datetime | None = None,
    home: Path | None = None,
) -> tuple[PortfolioDecision, PortfolioTurnResult | None]:
    """Request one automated worker turn without bypassing account fairness.

    Project-scoped autonomous commands yield when the portfolio selects another
    registered project. They never execute another project's work implicitly.
    """
    root = project_root.resolve()
    config = load_project_config(root)
    decision = collect_portfolio_decision(
        config.quota.account,
        now=now,
        home=home,
        persist=True,
    )
    if decision.account_busy:
        return decision, None
    if decision.selected_project_instance_id != project_instance_id(root):
        return decision, None

    candidate = _selected_candidate(decision)
    return (
        decision,
        _execute_selected(
            decision,
            candidate,
            requested_strategy=requested_strategy,
            fallback=fallback,
        ),
    )



def maintain_portfolio_projects(
    account_id: str,
    *,
    home: Path | None = None,
    now: datetime | None = None,
) -> tuple[list, list[str]]:
    """Advance non-worker phases for every registered project on one account."""
    if not account_id.strip():
        raise PortfolioError(
            "Portfolio maintenance requires a non-empty quota account id."
        )
    account_id = account_id.strip()
    now = now or utc_now()
    home = (home or projectctl_home()).resolve()
    results = []
    errors: list[str] = []

    for registration in _registrations(home):
        root = registration.project_root
        try:
            if not root.exists() or not root.is_dir():
                continue
            if git_root(root) != root:
                continue
            if project_instance_id(root) != registration.project_instance_id:
                continue
            config = load_project_config(root)
            if (
                config.project.id != registration.project_id
                or config.quota.account != account_id
            ):
                continue
            require_project_execution_ready(root)
            results.append(advance_non_worker_phases(root))
            _touch_registration(home, registration, observed_at=now)
        except ProjectCtlError as exc:
            errors.append(
                f"{registration.project_id}/"
                f"{registration.project_instance_id}: {exc}"
            )
        except Exception as exc:
            errors.append(
                f"{registration.project_id}/"
                f"{registration.project_instance_id}: "
                f"{type(exc).__name__}: {exc}"
            )
    return results, errors


def run_portfolio_cycle(
    account_id: str,
    *,
    now: datetime | None = None,
    home: Path | None = None,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> PortfolioCycleResult:
    """Advance all non-worker phases, then execute at most one fair worker turn."""
    now = now or utc_now()
    home = (home or projectctl_home()).resolve()
    maintenance, errors = maintain_portfolio_projects(
        account_id,
        home=home,
        now=now,
    )
    decision = collect_portfolio_decision(
        account_id,
        now=now,
        home=home,
        persist=True,
    )
    turn = None
    if (
        not decision.account_busy
        and decision.selected_project_instance_id is not None
    ):
        candidate = _selected_candidate(decision)
        turn = _execute_selected(
            decision,
            candidate,
            requested_strategy=requested_strategy,
            fallback=fallback,
        )

    return PortfolioCycleResult(
        generated_at=utc_now(),
        account_id=account_id.strip(),
        maintenance=maintenance,
        maintenance_errors=errors,
        decision=decision,
        turn=turn,
    )
