"""M6.0 M0g — cgroup v2 + service metadata are *observations*, not admission.

No actual systemctl, cgroup mutation, mount operation, signal, database
migration or operator permission change occurs here. Everything writable is
limited to disposable pytest tmp_path ProjectCTL v2 projects.

The Linux child tests demonstrate both that setsid does not leave a cgroup,
and that an independent unconfined process can write even if synthetic
systemd/cgroup observations describe an apparently stopped service.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

_RUN = "run-m0g"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)

# A disposable v2 writer, launched as an independent Python interpreter;
# no outside process, systemd unit, service name or file is ever modified.
_WRITER = r"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from projectctl.storage.runs import RunStore

root = Path(sys.argv[1])
do_setsid = sys.argv[2] == "setsid"
store = RunStore(root)  # preexisting legacy-v2 writer
before = Path("/proc/self/cgroup").read_text(encoding="utf-8")
group_before = os.getpgrp()
if do_setsid:
    os.setsid()
group_after = os.getpgrp()
after = Path("/proc/self/cgroup").read_text(encoding="utf-8")
store.append_event(
    "run-m0g", "m0g.fixture", {"disposable": True},
    now=datetime(2026, 10, 17, tzinfo=timezone.utc),
)
print(json.dumps({
    "before": before, "after": after,
    "group_before": group_before, "group_after": group_after,
    "pid": os.getpid()
}), flush=True)
"""


class ObservationRefused(ValueError):
    """A source sample was malformed or incomplete: never guess."""


def _cgroup_v2_path(raw: str) -> str:
    """Strict unified v2 membership, no v1/hybrid/malformed fallback."""
    if not isinstance(raw, str):
        raise ObservationRefused("invalid_proc_cgroup")
    lines = raw.splitlines()
    if len(lines) != 1:
        raise ObservationRefused("ambiguous_or_legacy_cgroup")
    prefix, sep, path = lines[0].partition("::")
    if not sep or prefix != "0" or not path.startswith("/"):
        raise ObservationRefused("not_unified_cgroup_v2")
    if path != "/" and (path.endswith("/") or "//" in path):
        raise ObservationRefused("invalid_cgroup_path")
    if any(part in ("", ".", "..") for part in path.split("/")[1:]):
        if path != "/":
            raise ObservationRefused("invalid_cgroup_path")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise ObservationRefused("invalid_cgroup_path")
    return path


def _pairs(raw: str, *, delimiter: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or delimiter not in line:
            raise ObservationRefused("malformed_property")
        key, value = line.split(delimiter, 1)
        if not key or key in out:
            raise ObservationRefused("duplicate_or_empty_property")
        out[key] = value.strip()
    return out


def _events(raw: str) -> tuple[int, int]:
    data = _pairs(raw, delimiter=" ")
    if "populated" not in data or "frozen" not in data:
        raise ObservationRefused("incomplete_cgroup_events")
    if data["populated"] not in ("0", "1") or data["frozen"] not in ("0", "1"):
        raise ObservationRefused("invalid_cgroup_events")
    return int(data["populated"]), int(data["frozen"])


def _procs(raw: str) -> tuple[int, ...]:
    if not isinstance(raw, str):
        raise ObservationRefused("invalid_cgroup_procs")
    lines = raw.splitlines()
    if len(lines) > 10000:
        raise ObservationRefused("process_list_exceeds_probe_limit")
    pids: list[int] = []
    for entry in lines:
        if not entry.isdecimal() or entry.startswith("0"):
            raise ObservationRefused("invalid_cgroup_pid")
        pids.append(int(entry))
    if len(pids) != len(set(pids)):
        raise ObservationRefused("duplicate_cgroup_pid")
    return tuple(sorted(pids))


@dataclass(frozen=True)
class UnitObservation:
    active_state: str
    sub_state: str
    control_group: str
    restart: str
    triggered_by: str
    unit_file_state: str


def _unit(raw: str) -> UnitObservation:
    data = _pairs(raw, delimiter="=")
    fields = (
        "ActiveState", "SubState", "ControlGroup", "Restart",
        "TriggeredBy", "UnitFileState",
    )
    if any(field not in data for field in fields):
        raise ObservationRefused("incomplete_systemd_properties")
    if not data["ControlGroup"].startswith("/"):
        raise ObservationRefused("missing_systemd_cgroup_identity")
    return UnitObservation(*(data[field] for field in fields))


@dataclass(frozen=True)
class DeploymentEvidence:
    """No field attests its own truth or grants any mutation authority."""

    expected_scope: str
    observed_scope: str
    unit: UnitObservation
    populated: int
    frozen: int
    member_pids: tuple[int, ...]
    source_identity_verified: bool = False
    all_external_writers_excluded: bool = False
    startup_embargo_independently_enforced: bool = False
    preopened_writer_fds_drained: bool = False
    namespace_and_mount_aliases_excluded: bool = False
    supervisor_restarts_blocked: bool = False
    backup_and_recovery_validated: bool = False


def _review(evidence: DeploymentEvidence) -> str:
    """Read-only NO-GO evidence triage; NEVER returns authority to migrate."""
    if (not evidence.expected_scope.startswith("/")
            or evidence.expected_scope == "/"
            or evidence.observed_scope != evidence.expected_scope
            or evidence.unit.control_group != evidence.expected_scope):
        return "NO_GO_CGROUP_SCOPE_MISMATCH"
    if evidence.populated != 0 or evidence.member_pids:
        # cgroup.procs empty can hide descendants in populated subgroups.
        return "NO_GO_CGROUP_STILL_POPULATED"
    if evidence.frozen != 0:
        return "NO_GO_FROZEN_IS_NOT_STOPPED"
    if evidence.unit.active_state != "inactive" or evidence.unit.sub_state != "dead":
        return "NO_GO_SYSTEMD_UNIT_NOT_STOPPED"
    if (evidence.unit.restart != "no"
            or evidence.unit.triggered_by
            or evidence.unit.unit_file_state not in ("disabled", "masked")):
        # Even a masked unit is NOT a global start embargo.
        return "NO_GO_SERVICE_REACTIVATION"
    for gate in (
        "source_identity_verified",
        "all_external_writers_excluded",
        "startup_embargo_independently_enforced",
        "preopened_writer_fds_drained",
        "namespace_and_mount_aliases_excluded",
        "supervisor_restarts_blocked",
        "backup_and_recovery_validated",
    ):
        if not getattr(evidence, gate):
            return "NO_GO_" + gate.upper()
    return "OPERATOR_REVIEW_ONLY"


def _candidate() -> DeploymentEvidence:
    scope = "/system.slice/projectctl-disposable.service"
    return DeploymentEvidence(
        expected_scope=scope,
        observed_scope=scope,
        unit=UnitObservation("inactive", "dead", scope, "no", "", "masked"),
        populated=0, frozen=0, member_pids=(),
    )


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "m0g-disposable"
    initialize_project_state_db(root / ".projectctl" / "state.sqlite")
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0g",
            execution_plan_digest="m0g-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0g",
            worktree_id="run-m0g",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-real-worktree",
        now=_NOW,
    )
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    return root, store


def test_strict_cgroup_v2_parsing_rejects_ambiguous_v1_and_traversal():
    assert _cgroup_v2_path("0::/\n") == "/"
    assert _cgroup_v2_path("0::/system.slice/projectctl.service\n") == (
        "/system.slice/projectctl.service"
    )
    bad = (
        "", "2:cpu:/\n", "0::/a\n1:name=systemd:/b\n",
        "0::a", "0::/a/../b", "0::/a//b", "0::/a/./b",
        "0::/a/", "0::/a\x00b",
    )
    for sample in bad:
        with pytest.raises(ObservationRefused):
            _cgroup_v2_path(sample)


def test_systemd_and_kernel_metadata_reject_incomplete_or_duplicate():
    assert _events("populated 0\nfrozen 0\n") == (0, 0)
    assert _events("populated 1\nfrozen 0\n") == (1, 0)
    for bad in (
        "", "populated 0\n", "populated 2\nfrozen 0\n",
        "populated 0\npopulated 0\nfrozen 0\n",
    ):
        with pytest.raises(ObservationRefused):
            _events(bad)
    assert _procs("123\n456\n") == (123, 456)
    for bad in ("0\n", "123\n123\n", "-1\n", "abc\n"):
        with pytest.raises(ObservationRefused):
            _procs(bad)
    unit = (
        "ActiveState=inactive\nSubState=dead\n"
        "ControlGroup=/system.slice/projectctl-disposable.service\n"
        "Restart=no\nTriggeredBy=\nUnitFileState=masked\n"
    )
    assert _unit(unit) == _candidate().unit
    for bad in (unit + "Restart=always\n", unit.replace("ControlGroup=/system.slice/projectctl-disposable.service\n", "")):
        with pytest.raises(ObservationRefused):
            _unit(bad)


def test_empty_direct_cgroup_procs_not_sufficient_when_subgroups_populated():
    # Synthetic metadata models a real cgroup v2 semantic: cgroup.events
    # populated=1 also reflects live processes in descendant cgroups.
    event = _events("populated 1\nfrozen 0\n")
    assert _procs("") == ()
    current = replace(_candidate(), populated=event[0], member_pids=_procs(""))
    assert _review(current) == "NO_GO_CGROUP_STILL_POPULATED"


def test_unit_inactive_or_masked_never_proves_outside_writer_exclusion():
    assert _review(_candidate()) == "NO_GO_SOURCE_IDENTITY_VERIFIED"
    assert _review(replace(
        _candidate(), unit=replace(_candidate().unit, restart="always")
    )) == "NO_GO_SERVICE_REACTIVATION"
    assert _review(replace(
        _candidate(), unit=replace(_candidate().unit, triggered_by="projectctl.socket")
    )) == "NO_GO_SERVICE_REACTIVATION"
    assert _review(replace(
        _candidate(), unit=replace(_candidate().unit, active_state="active")
    )) == "NO_GO_SYSTEMD_UNIT_NOT_STOPPED"
    assert _review(replace(
        _candidate(), frozen=1
    )) == "NO_GO_FROZEN_IS_NOT_STOPPED"
    assert _review(replace(
        _candidate(), observed_scope="/other.slice/another.service"
    )) == "NO_GO_CGROUP_SCOPE_MISMATCH"


def test_all_external_claims_required_and_still_never_production_go():
    base = _candidate()
    gates = (
        "source_identity_verified",
        "all_external_writers_excluded",
        "startup_embargo_independently_enforced",
        "preopened_writer_fds_drained",
        "namespace_and_mount_aliases_excluded",
        "supervisor_restarts_blocked",
        "backup_and_recovery_validated",
    )
    fully_claimed = replace(base, **{gate: True for gate in gates})
    assert _review(fully_claimed) == "OPERATOR_REVIEW_ONLY"
    for gate in gates:
        assert _review(replace(fully_claimed, **{gate: False})) == (
            "NO_GO_" + gate.upper()
        )


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="M0g actual proc/cgroup Linux behavior",
)
@pytest.mark.parametrize("escape_session", [True, False])
def test_actual_setsid_cannot_change_cgroup_or_confer_writer_exclusion(
    tmp_path, escape_session,
):
    root, store = _fixture(tmp_path)
    try:
        parent_membership = _cgroup_v2_path(
            Path("/proc/self/cgroup").read_text(encoding="utf-8")
        )
    except (ObservationRefused, OSError):
        pytest.skip("unified cgroup v2 /proc source not available")
    before = len(store.events(_RUN))
    proc = subprocess.run(
        [
            sys.executable, "-c", _WRITER, str(root),
            "setsid" if escape_session else "normal",
        ],
        capture_output=True, text=True, timeout=15, check=True,
    )
    result = json.loads(proc.stdout)
    assert _cgroup_v2_path(result["before"]) == parent_membership
    assert _cgroup_v2_path(result["after"]) == parent_membership
    if escape_session:
        assert result["group_before"] != result["group_after"]
        assert result["group_after"] == result["pid"]
    assert len(store.events(_RUN)) == before + 1
    assert store.events(_RUN)[-1].event_type == "m0g.fixture"
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    # Unlike M0f's process group, cgroup membership survives setsid.
    # The child was never put into a stopped/enforced service cgroup;
    # its successful write is a deliberate negative authorization proof.
    assert _review(_candidate()) == "NO_GO_SOURCE_IDENTITY_VERIFIED"


def test_project_db_version_unchanged_and_no_service_mutation(tmp_path):
    root, store = _fixture(tmp_path)
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    assert PROJECT_STATE_DB_VERSION == 2
    assert not (root / ".projectctl" / "m0g-evidence.json").exists()
