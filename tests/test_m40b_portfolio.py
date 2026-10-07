from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from projectctl.application import portfolio as portfolio_app
from projectctl.cli.entry import app
from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus
from projectctl.schemas.orchestration import ProjectTurnEnvelope, ProjectTurnResult
from projectctl.schemas.portfolio import (
    PortfolioCandidate,
    PortfolioDecision,
    PortfolioDecisionV1,
)
from projectctl.application.portfolio import ProjectRegistration

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
runner = CliRunner()


def registration(instance: str, project: str, minutes: int) -> ProjectRegistration:
    return ProjectRegistration(
        project_instance_id=instance,
        project_id=project,
        project_root=Path(f"/tmp/{project}"),
        registered_at=NOW - timedelta(minutes=minutes),
        last_seen_at=NOW - timedelta(minutes=minutes),
    )


def turn(
    reg: ProjectRegistration,
    *,
    action: str,
    active_count: int = 0,
    max_active: int = 1,
    parallel_admission: bool = False,
) -> ProjectTurnEnvelope:
    run_id = (
        f"run-{reg.project_id}"
        if action in {"resume_run", "start_run"}
        else None
    )
    return ProjectTurnEnvelope(
        envelope_id=f"turn-{reg.project_id}",
        observed_at=NOW,
        project_instance_id=reg.project_instance_id,
        project_id=reg.project_id,
        project_root=str(reg.project_root),
        account_id="acct",
        eligible=True,
        action=action,
        run_id=run_id,
        run_status=(
            RunStatus.RUNNING
            if action == "resume_run"
            else RunStatus.CLAIMED
            if action == "start_run"
            else None
        ),
        task_id="task-" + reg.project_id,
        resource_class=ResourceClass.SMALL,
        project_state_digest="state-" + reg.project_id,
        task_snapshot_digest="tasks-" + reg.project_id,
        quota_snapshot_digest="quota-" + reg.project_id,
        quota_mode=QuotaMode.NORMAL,
        quota_stale=False,
        active_run_ids=[
            f"active-{reg.project_id}-{i}" for i in range(active_count)
        ],
        active_run_count=active_count,
        max_active_runs=max_active,
        parallel_admission=parallel_admission,
    )


def candidate(
    reg: ProjectRegistration,
    *,
    action: str,
    last_admitted_at=None,
    active_count: int = 0,
    max_active: int = 1,
    parallel_admission: bool = False,
) -> PortfolioCandidate:
    envelope = turn(
        reg,
        action=action,
        active_count=active_count,
        max_active=max_active,
        parallel_admission=parallel_admission,
    )
    return PortfolioCandidate(
        project_instance_id=reg.project_instance_id,
        project_id=reg.project_id,
        project_root=str(reg.project_root),
        registered_at=reg.registered_at,
        last_seen_at=reg.last_seen_at,
        observed_at=NOW,
        account_id="acct",
        eligible=True,
        action=action,
        run_id=envelope.run_id,
        run_status=envelope.run_status,
        selected_task_id=envelope.task_id,
        project_state_digest=envelope.project_state_digest,
        task_snapshot_digest=envelope.task_snapshot_digest,
        quota_snapshot_digest=envelope.quota_snapshot_digest,
        quota_mode=QuotaMode.NORMAL,
        quota_stale=False,
        resource_class=ResourceClass.SMALL,
        last_admitted_at=last_admitted_at,
        active_run_ids=envelope.active_run_ids,
        active_run_count=active_count,
        max_active_runs=max_active,
        parallel_admission=parallel_admission,
        turn=envelope,
    )


class FakeAdmissionStore:
    active = None
    history = {}

    def __init__(self, *args, **kwargs):
        pass

    def get(self, account_id):
        return self.active

    def last_acquired_at_by_project(self, account_id):
        return dict(self.history)


def setup_collection(monkeypatch, registrations, candidates):
    FakeAdmissionStore.active = None
    FakeAdmissionStore.history = {
        item.project_instance_id: item.last_admitted_at
        for item in candidates
        if item.last_admitted_at is not None
    }
    by_instance = {
        item.project_instance_id: item for item in candidates
    }
    monkeypatch.setattr(
        portfolio_app,
        "_registrations",
        lambda home: registrations,
    )
    monkeypatch.setattr(
        portfolio_app,
        "AccountAdmissionStore",
        FakeAdmissionStore,
    )
    monkeypatch.setattr(
        portfolio_app,
        "_inspect_registration",
        lambda reg, **kwargs: by_instance[reg.project_instance_id],
    )


def test_continuation_has_priority_over_new_work(monkeypatch, tmp_path):
    admit_reg = registration("instance-new", "new-project", 30)
    resume_reg = registration("instance-resume", "resume-project", 10)
    candidates = [
        candidate(admit_reg, action="admit_task"),
        candidate(
            resume_reg,
            action="resume_run",
            last_admitted_at=NOW - timedelta(minutes=1),
        ),
    ]
    setup_collection(monkeypatch, [admit_reg, resume_reg], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.schema_version == 2
    assert decision.selected_project_instance_id == "instance-resume"
    assert decision.selected_action == "resume_run"


def test_same_action_uses_least_recently_admitted_fairness(
    monkeypatch, tmp_path
):
    older = registration("instance-a", "project-a", 30)
    newer = registration("instance-b", "project-b", 20)
    candidates = [
        candidate(
            older,
            action="admit_task",
            last_admitted_at=NOW - timedelta(hours=3),
        ),
        candidate(
            newer,
            action="admit_task",
            last_admitted_at=NOW - timedelta(hours=1),
        ),
    ]
    setup_collection(monkeypatch, [older, newer], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-a"


def test_never_admitted_project_wins_same_action_fairness(
    monkeypatch, tmp_path
):
    never = registration("instance-never", "project-never", 10)
    used = registration("instance-used", "project-used", 30)
    candidates = [
        candidate(never, action="admit_task"),
        candidate(
            used,
            action="admit_task",
            last_admitted_at=NOW - timedelta(days=1),
        ),
    ]
    setup_collection(monkeypatch, [never, used], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-never"


def test_live_account_admission_blocks_portfolio_selection(
    monkeypatch, tmp_path
):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(reg, action="admit_task")
    setup_collection(monkeypatch, [reg], [cand])
    FakeAdmissionStore.active = SimpleNamespace(
        project_instance_id="instance-live",
        run_id="run-live",
        expires_at=NOW + timedelta(minutes=1),
    )

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.account_busy is True
    assert decision.selected_project_instance_id is None
    assert decision.active_run_id == "run-live"


def test_portfolio_candidate_contract_has_no_project_local_score():
    fields = PortfolioCandidate.model_fields
    assert "score" not in fields
    assert "score_breakdown" not in fields
    assert "turn" in fields


def test_parallel_active_set_candidate_remains_portfolio_eligible(
    monkeypatch, tmp_path
):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(
        reg,
        action="admit_task",
        active_count=2,
        max_active=3,
        parallel_admission=True,
    )
    setup_collection(monkeypatch, [reg], [cand])

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-a"
    assert decision.candidates[0].active_run_count == 2
    assert decision.candidates[0].parallel_admission is True


def test_run_portfolio_turn_executes_selected_project_envelope(
    monkeypatch, tmp_path
):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(reg, action="admit_task")
    decision = PortfolioDecision(
        decision_id="portfolio-test",
        evaluated_at=NOW,
        account_id="acct",
        registry_digest="registry",
        selected_project_instance_id=cand.project_instance_id,
        selected_project_id=cand.project_id,
        selected_project_root=cand.project_root,
        selected_action="admit_task",
        selected_task_id=cand.selected_task_id,
        candidates=[cand],
    )
    monkeypatch.setattr(
        portfolio_app,
        "collect_portfolio_decision",
        lambda *args, **kwargs: decision,
    )

    observed = {}

    def execute(root, envelope, **kwargs):
        observed["root"] = root
        observed["envelope"] = envelope
        return ProjectTurnResult(
            envelope=envelope,
            run_id="run-new",
            run_status=RunStatus.VERIFYING,
            prepared_new_run=True,
        )

    monkeypatch.setattr(portfolio_app, "execute_project_turn", execute)

    result = portfolio_app.run_portfolio_turn("acct", home=tmp_path)

    assert result.action == "admit_task"
    assert result.run_id == "run-new"
    assert result.project_turn.prepared_new_run is True
    assert observed["envelope"].task_id == cand.selected_task_id


def test_request_fair_project_turn_yields_to_other_project(
    monkeypatch, tmp_path
):
    root = tmp_path / "local"
    root.mkdir()
    monkeypatch.setattr(
        portfolio_app,
        "load_project_config",
        lambda value: SimpleNamespace(
            quota=SimpleNamespace(account="acct")
        ),
    )
    monkeypatch.setattr(
        portfolio_app,
        "project_instance_id",
        lambda value: "instance-local",
    )
    decision = PortfolioDecision(
        decision_id="portfolio-test",
        evaluated_at=NOW,
        account_id="acct",
        registry_digest="registry",
        selected_project_instance_id="instance-other",
        selected_project_id="other",
        selected_project_root="/tmp/other",
        selected_action="admit_task",
        selected_task_id="task-other",
        candidates=[],
    )
    monkeypatch.setattr(
        portfolio_app,
        "collect_portfolio_decision",
        lambda *args, **kwargs: decision,
    )

    observed_decision, result = portfolio_app.request_fair_project_turn(root)

    assert observed_decision is decision
    assert result is None


def test_portfolio_v1_contract_remains_constructible():
    legacy = PortfolioDecisionV1(
        decision_id="legacy",
        evaluated_at=NOW,
        account_id="acct",
        registry_digest="registry",
        selected_action="new_task",
    )
    assert legacy.schema_version == 1
    assert legacy.selected_action == "new_task"


def test_portfolio_cli_is_registered():
    result = runner.invoke(app, ["portfolio", "--help"])
    assert result.exit_code == 0, result.output
    assert "next" in result.output
    assert "run" in result.output
