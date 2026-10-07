from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from projectctl.application.execution_inputs import (
    execution_input_path_allowed,
    finalize_execution_input,
    semantic_execution_input_digest,
)
from projectctl.core.enums import ResourceClass, TaskStatus, TaskType
from projectctl.core.errors import StaleSnapshotError
from projectctl.core.digest import digest
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.scheduler.digests import semantic_task_scope_digest
from projectctl.schemas.execution_input import ExecutionInputManifest, ExecutionPathScope
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource
from projectctl.schemas.task_claim import TaskClaim

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)


def task(
    task_id: str,
    *,
    status: TaskStatus = TaskStatus.READY,
    revision: str = "r1",
    title: str | None = None,
    dependencies: list[str] | None = None,
    observed_at: datetime = NOW,
) -> NormalizedTask:
    return NormalizedTask(
        id=task_id,
        title=title or task_id,
        source=TaskSource(
            provider="beads",
            external_id=task_id,
            revision=revision,
            observed_at=observed_at,
        ),
        type=TaskType.TASK,
        status=status,
        resource_class=ResourceClass.SMALL,
        dependencies=dependencies or [],
    )


def snapshot(*values: NormalizedTask) -> TaskSnapshot:
    return TaskSnapshot(
        provider="beads",
        captured_at=NOW,
        source_revision="snapshot",
        tasks=list(values),
    )


def preclaim_manifest(before: TaskSnapshot) -> ExecutionInputManifest:
    scoped_digest, scoped_ids = semantic_task_scope_digest(before, "a")
    by_id = {item.id: item for item in before.tasks}
    return ExecutionInputManifest(
        project_id="repo",
        task_id="a",
        task_provider="beads",
        scheduler_task_snapshot_digest="scheduler-snapshot",
        project_state_digest="project-state",
        preclaim_task_scope_digest=scoped_digest,
        admitted_task_scope_digest=scoped_digest,
        scoped_task_ids=scoped_ids,
        preclaim_tasks=[by_id[item] for item in scoped_ids],
        base_commit="a" * 40,
        integration_target_ref="main",
        phase="preclaim",
        created_at=NOW,
    )


def acquired_claim() -> TaskClaim:
    return TaskClaim(
        provider="beads",
        task_id="a",
        run_id="run-a",
        actor="projectctl:test",
        base_commit="a" * 40,
        integration_target_ref="main",
        claim_token="c" * 32,
        request_digest="claim-request",
        acquired=True,
        observed_at=NOW,
    )


def test_beads_expected_claim_transition_is_admitted_while_unrelated_task_moves(
    tmp_path: Path,
):
    before = snapshot(
        task("a", dependencies=["b"]),
        task("b"),
        task("c", title="unrelated-before"),
    )
    after = snapshot(
        task(
            "a",
            status=TaskStatus.RUNNING,
            revision="r2",
            dependencies=["b"],
        ),
        task("b"),
        task("c", title="unrelated-after"),
    )
    claimer = BeadsTaskClaimer(tmp_path, client=object())

    admitted = finalize_execution_input(
        preclaim_manifest(before),
        before_snapshot=before,
        after_snapshot=after,
        claim=acquired_claim(),
        claimer=claimer,
        now=NOW + timedelta(seconds=1),
    )

    assert admitted.phase == "admitted"
    assert admitted.claim_transition is not None
    assert admitted.claim_transition.transition_kind == "provider_native"
    assert admitted.scoped_task_ids == ["a", "b"]
    assert admitted.admitted_task_scope_digest != admitted.preclaim_task_scope_digest


def test_beads_claim_transition_rejects_relevant_dependency_drift(tmp_path: Path):
    before = snapshot(
        task("a", dependencies=["b"]),
        task("b", title="dependency-before"),
    )
    after = snapshot(
        task(
            "a",
            status=TaskStatus.RUNNING,
            revision="r2",
            dependencies=["b"],
        ),
        task("b", title="dependency-after"),
    )
    claimer = BeadsTaskClaimer(tmp_path, client=object())

    with pytest.raises(StaleSnapshotError, match="dependency"):
        finalize_execution_input(
            preclaim_manifest(before),
            before_snapshot=before,
            after_snapshot=after,
            claim=acquired_claim(),
            claimer=claimer,
        )


def test_beads_claim_transition_rejects_extra_selected_task_mutation(tmp_path: Path):
    before = snapshot(task("a", title="before"))
    after = snapshot(
        task(
            "a",
            status=TaskStatus.RUNNING,
            revision="r2",
            title="changed by something else",
        )
    )
    claimer = BeadsTaskClaimer(tmp_path, client=object())

    with pytest.raises(StaleSnapshotError, match="expected consequence"):
        finalize_execution_input(
            preclaim_manifest(before),
            before_snapshot=before,
            after_snapshot=after,
            claim=acquired_claim(),
            claimer=claimer,
        )


class NoTransitionSemanticsClaimer:
    pass


def test_claimer_without_transition_semantics_accepts_only_unchanged_task():
    before = snapshot(task("a"))
    same = snapshot(
        task(
            "a",
            observed_at=NOW + timedelta(minutes=1),
        )
    )
    admitted = finalize_execution_input(
        preclaim_manifest(before),
        before_snapshot=before,
        after_snapshot=same,
        claim=acquired_claim(),
        claimer=NoTransitionSemanticsClaimer(),
    )
    assert admitted.claim_transition is not None
    assert admitted.claim_transition.transition_kind == "unchanged"

    changed = snapshot(
        task(
            "a",
            status=TaskStatus.RUNNING,
            revision="r2",
        )
    )
    with pytest.raises(StaleSnapshotError):
        finalize_execution_input(
            preclaim_manifest(before),
            before_snapshot=before,
            after_snapshot=changed,
            claim=acquired_claim(),
            claimer=NoTransitionSemanticsClaimer(),
        )


def test_execution_input_digest_ignores_observation_time_only():
    before = snapshot(task("a", observed_at=NOW))
    first = preclaim_manifest(before)
    shifted_task = task("a", observed_at=NOW + timedelta(hours=1))
    second = first.model_copy(
        update={
            "preclaim_tasks": [shifted_task],
            "created_at": NOW + timedelta(hours=1),
        }
    )
    assert semantic_execution_input_digest(first) == semantic_execution_input_digest(second)

    materially_changed = second.model_copy(
        update={"preclaim_tasks": [task("a", title="different")]}
    )
    assert semantic_execution_input_digest(first) != semantic_execution_input_digest(
        materially_changed
    )


def test_execution_scope_exact_and_tree_authorization():
    scopes = [
        ExecutionPathScope(path="src/core.py", kind="exact"),
        ExecutionPathScope(path="tests/unit", kind="tree"),
    ]
    assert execution_input_path_allowed(scopes, "src/core.py")
    assert not execution_input_path_allowed(scopes, "src/other.py")
    assert execution_input_path_allowed(scopes, "tests/unit/test_a.py")
    assert not execution_input_path_allowed(scopes, "tests/integration/test_a.py")
