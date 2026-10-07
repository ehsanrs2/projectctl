from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from projectctl.application.execution import (
    prepare_next_run,
    resume_checkpointed_run,
    start_prepared_run,
)
from projectctl.application.status import collect_status
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus
from projectctl.core.errors import PortfolioError, ProjectCtlError
from projectctl.core.time import utc_now
from projectctl.project.root import git_root
from projectctl.project.bootstrap import _global_init, projectctl_home
from projectctl.integrations.execution_ownership import require_project_execution_ready
from projectctl.project.loader import load_project_config
from projectctl.quota import QuotaManager
from projectctl.quota.admission import AccountAdmissionStore, project_instance_id
from projectctl.schemas.portfolio import (
    PortfolioCandidate,
    PortfolioDecision,
    PortfolioTurnResult,
)
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import connect_db


_ACTIVE_RUN_STATUSES = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
}

_ACTION_RANK = {
    "resume_run": 0,
    "start_run": 1,
    "new_task": 2,
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


def _active_runs(store: RunStore):
    return [
        record
        for record in store.list(limit=1000)
        if record.status in _ACTIVE_RUN_STATUSES
    ]


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
            update={
                "account_id": config.quota.account,
            }
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

        store = RunStore(root)
        active = _active_runs(store)
        if len(active) > 1:
            return _excluded(
                candidate,
                "multiple_active_runs",
                ",".join(sorted(record.run_id for record in active)),
            )

        status = collect_status(root, now=now, record_telemetry=False)
        candidate = candidate.model_copy(
            update={
                "project_state_digest": status.decision.project_state_digest,
                "task_snapshot_digest": status.decision.task_snapshot_digest,
                "quota_snapshot_digest": status.decision.quota_snapshot_digest,
                "quota_mode": status.quota_state.mode,
                "quota_stale": status.quota_state.stale,
            }
        )

        if status.quota_state.stale:
            return _excluded(candidate, "quota_stale")

        action = None
        run_id = None
        run_status = None
        task_id = None

        if active:
            record = active[0]
            run_id = record.run_id
            run_status = record.status
            if (
                record.lease_owner is not None
                and record.lease_expires_at is not None
                and record.lease_expires_at > now
            ):
                return _excluded(candidate, "active_run_leased")

            if record.status == RunStatus.RUNNING and record.checkpoint_ref:
                action = "resume_run"
                task_id = record.task_id
            elif record.status == RunStatus.CLAIMED:
                action = "start_run"
                task_id = record.task_id
            elif record.status in {
                RunStatus.VERIFYING,
                RunStatus.READY_TO_INTEGRATE,
                RunStatus.INTEGRATING,
                RunStatus.AWAITING_REVIEW,
            }:
                return _excluded(candidate, "non_worker_phase_pending")
            else:
                return _excluded(candidate, "run_recovery_required")
        else:
            task_id = status.decision.selected_task_id
            if task_id is None:
                return _excluded(candidate, "no_eligible_task")
            action = "new_task"

        task = next((item for item in status.tasks.tasks if item.id == task_id), None)
        if task is None:
            return _excluded(
                candidate,
                "selected_task_missing",
                f"task_id={task_id}",
            )

        manager = QuotaManager(config.quota)
        if not manager.eligible_for_resource(task.resource_class, status.quota_state):
            return _excluded(candidate, "quota_insufficient")

        return candidate.model_copy(
            update={
                "eligible": True,
                "action": action,
                "run_id": run_id,
                "run_status": run_status,
                "selected_task_id": task_id,
                "resource_class": task.resource_class,
            }
        )
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
        raise PortfolioError("Portfolio arbitration requires a non-empty quota account id.")

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
        selected_project_id=selected.project_id if selected is not None else None,
        selected_project_root=selected.project_root if selected is not None else None,
        selected_action=selected.action if selected is not None else None,
        selected_run_id=selected.run_id if selected is not None else None,
        selected_task_id=selected.selected_task_id if selected is not None else None,
        candidates=candidates,
    )

    if persist:
        _atomic_json(
            home / "portfolio" / "decisions" / f"{decision.decision_id}.json",
            decision,
        )
    return decision


def run_portfolio_turn(
    account_id: str,
    *,
    now: datetime | None = None,
    home: Path | None = None,
) -> PortfolioTurnResult:
    decision = collect_portfolio_decision(
        account_id,
        now=now,
        home=home,
        persist=True,
    )
    if decision.account_busy:
        raise PortfolioError(
            f"Quota account {account_id!r} already has an active worker-turn admission "
            f"for run {decision.active_run_id}."
        )
    if decision.selected_project_instance_id is None:
        raise PortfolioError(
            f"No registered project is eligible for the next worker turn on account "
            f"{account_id!r}."
        )

    candidate = next(
        item
        for item in decision.candidates
        if item.project_instance_id == decision.selected_project_instance_id
    )
    if candidate.action is None or candidate.selected_task_id is None:
        raise PortfolioError("Selected portfolio candidate is incomplete.")

    root = Path(candidate.project_root).resolve()
    if candidate.action == "resume_run":
        if candidate.run_id is None:
            raise PortfolioError("Resume candidate is missing run identity.")
        started = resume_checkpointed_run(root, candidate.run_id)
    elif candidate.action == "start_run":
        if candidate.run_id is None:
            raise PortfolioError("Start candidate is missing run identity.")
        started = start_prepared_run(root, candidate.run_id)
    else:
        if (
            candidate.task_snapshot_digest is None
            or candidate.project_state_digest is None
        ):
            raise PortfolioError(
                "New-task portfolio candidate is missing scheduler input digests."
            )
        prepared = prepare_next_run(
            root,
            expected_task_id=candidate.selected_task_id,
            expected_task_snapshot_digest=candidate.task_snapshot_digest,
            expected_project_state_digest=candidate.project_state_digest,
        )
        started = start_prepared_run(root, prepared.record.run_id)

    return PortfolioTurnResult(
        decision=decision,
        project_instance_id=candidate.project_instance_id,
        project_id=candidate.project_id,
        project_root=candidate.project_root,
        action=candidate.action,
        run_id=started.record.run_id,
        run_status=started.record.status,
    )
