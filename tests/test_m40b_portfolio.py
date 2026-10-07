from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from projectctl.application import portfolio as portfolio_app
from projectctl.cli.entry import app
from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus
from projectctl.schemas.portfolio import PortfolioCandidate, PortfolioDecision
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


def candidate(
    reg: ProjectRegistration,
    *,
    action: str,
    last_admitted_at=None,
) -> PortfolioCandidate:
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
        run_id=("run-" + reg.project_id) if action != "new_task" else None,
        run_status=(
            RunStatus.RUNNING
            if action == "resume_run"
            else RunStatus.CLAIMED
            if action == "start_run"
            else None
        ),
        selected_task_id="task-" + reg.project_id,
        project_state_digest="state-" + reg.project_id,
        task_snapshot_digest="tasks-" + reg.project_id,
        quota_snapshot_digest="quota-" + reg.project_id,
        quota_mode=QuotaMode.NORMAL,
        quota_stale=False,
        resource_class=ResourceClass.SMALL,
        last_admitted_at=last_admitted_at,
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
    by_instance = {item.project_instance_id: item for item in candidates}
    monkeypatch.setattr(portfolio_app, "_registrations", lambda home: registrations)
    monkeypatch.setattr(portfolio_app, "AccountAdmissionStore", FakeAdmissionStore)
    monkeypatch.setattr(
        portfolio_app,
        "_inspect_registration",
        lambda reg, **kwargs: by_instance[reg.project_instance_id],
    )


def test_continuation_has_priority_over_new_work(monkeypatch, tmp_path):
    new_reg = registration("instance-new", "new-project", 30)
    resume_reg = registration("instance-resume", "resume-project", 10)
    candidates = [
        candidate(new_reg, action="new_task"),
        candidate(
            resume_reg,
            action="resume_run",
            last_admitted_at=NOW - timedelta(minutes=1),
        ),
    ]
    setup_collection(monkeypatch, [new_reg, resume_reg], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-resume"
    assert decision.selected_action == "resume_run"


def test_same_action_uses_least_recently_admitted_fairness(monkeypatch, tmp_path):
    older = registration("instance-a", "project-a", 30)
    newer = registration("instance-b", "project-b", 20)
    candidates = [
        candidate(
            older,
            action="new_task",
            last_admitted_at=NOW - timedelta(hours=3),
        ),
        candidate(
            newer,
            action="new_task",
            last_admitted_at=NOW - timedelta(hours=1),
        ),
    ]
    setup_collection(monkeypatch, [older, newer], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-a"


def test_never_admitted_project_wins_same_action_fairness(monkeypatch, tmp_path):
    never = registration("instance-never", "project-never", 10)
    used = registration("instance-used", "project-used", 30)
    candidates = [
        candidate(never, action="new_task"),
        candidate(
            used,
            action="new_task",
            last_admitted_at=NOW - timedelta(days=1),
        ),
    ]
    setup_collection(monkeypatch, [never, used], candidates)

    decision = portfolio_app.collect_portfolio_decision(
        "acct", now=NOW, home=tmp_path, persist=False
    )

    assert decision.selected_project_instance_id == "instance-never"


def test_live_account_admission_blocks_portfolio_selection(monkeypatch, tmp_path):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(reg, action="new_task")
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


def test_run_portfolio_turn_binds_new_task_to_local_scheduler_inputs(
    monkeypatch, tmp_path
):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(reg, action="new_task")
    decision = PortfolioDecision(
        decision_id="portfolio-test",
        evaluated_at=NOW,
        account_id="acct",
        registry_digest="registry",
        selected_project_instance_id=cand.project_instance_id,
        selected_project_id=cand.project_id,
        selected_project_root=cand.project_root,
        selected_action="new_task",
        selected_task_id=cand.selected_task_id,
        candidates=[cand],
    )
    monkeypatch.setattr(
        portfolio_app,
        "collect_portfolio_decision",
        lambda *args, **kwargs: decision,
    )

    observed = {}

    def prepare(root, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(record=SimpleNamespace(run_id="run-new"))

    monkeypatch.setattr(portfolio_app, "prepare_next_run", prepare)
    monkeypatch.setattr(
        portfolio_app,
        "start_prepared_run",
        lambda root, run_id: SimpleNamespace(
            record=SimpleNamespace(run_id=run_id, status=RunStatus.VERIFYING)
        ),
    )

    result = portfolio_app.run_portfolio_turn("acct", home=tmp_path)

    assert result.action == "new_task"
    assert result.run_id == "run-new"
    assert observed["expected_task_id"] == cand.selected_task_id
    assert observed["expected_task_snapshot_digest"] == cand.task_snapshot_digest
    assert observed["expected_project_state_digest"] == cand.project_state_digest


def test_run_portfolio_turn_resumes_existing_checkpoint(monkeypatch, tmp_path):
    reg = registration("instance-a", "project-a", 30)
    cand = candidate(reg, action="resume_run")
    decision = PortfolioDecision(
        decision_id="portfolio-test",
        evaluated_at=NOW,
        account_id="acct",
        registry_digest="registry",
        selected_project_instance_id=cand.project_instance_id,
        selected_project_id=cand.project_id,
        selected_project_root=cand.project_root,
        selected_action="resume_run",
        selected_run_id=cand.run_id,
        selected_task_id=cand.selected_task_id,
        candidates=[cand],
    )
    monkeypatch.setattr(
        portfolio_app,
        "collect_portfolio_decision",
        lambda *args, **kwargs: decision,
    )
    monkeypatch.setattr(
        portfolio_app,
        "resume_checkpointed_run",
        lambda root, run_id: SimpleNamespace(
            record=SimpleNamespace(run_id=run_id, status=RunStatus.VERIFYING)
        ),
    )

    result = portfolio_app.run_portfolio_turn("acct", home=tmp_path)

    assert result.action == "resume_run"
    assert result.run_id == cand.run_id


def test_portfolio_cli_is_registered():
    result = runner.invoke(app, ["portfolio", "--help"])
    assert result.exit_code == 0, result.output
    assert "next" in result.output
    assert "run" in result.output
