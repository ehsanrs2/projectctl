"""Issue #127: exclusive lifecycle telemetry collisions stay pre-dispatch and quiet."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.telemetry.lifecycle import (
    MeasurementArtifactExistsError,
    measurement_artifact,
)
from test_m14_integration_recovery import setup_ready_run


@pytest.mark.parametrize(("stage", "function_name"), [
    ("start", "start_prepared_run"),
    ("resume", "resume_checkpointed_run"),
    ("verify", "verify_run"),
    ("integrate", "integrate_run"),
])
@pytest.mark.parametrize("initial_bytes", [
    b"PRIVATE-EXISTING-METRICS-DO-NOT-PRINT",
    b'{"state":"pending","authority":"telemetry_only_not_dispatch_authority"}',
])
@pytest.mark.parametrize("json_output", [False, True])
def test_duplicate_measurements_are_sanitized_and_cannot_enter_any_stage(
    tmp_path, monkeypatch, stage, function_name, initial_bytes, json_output
):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    metrics = tmp_path / "existing-measurements.json"
    metrics.write_bytes(initial_bytes)
    calls = []

    def must_not_start(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("COLLISION_MUST_NOT_REENTER_STAGE")

    monkeypatch.setattr("projectctl.cli.m11." + function_name, must_not_start)
    command = ["run", stage, run_id, "--project", str(repo),
               "--measurements", str(metrics)]
    if json_output:
        command.append("--json")
    result = CliRunner().invoke(app, command)

    assert result.exit_code == 17, result.output
    assert "Measurement artifact already exists" in result.output
    assert "new --measurements path" in result.output
    assert "never authorizes retry" in result.output
    assert "Traceback" not in result.output
    assert "COLLISION_MUST_NOT_REENTER_STAGE" not in result.output
    assert str(metrics) not in result.output
    assert str(repo) not in result.output
    assert "PRIVATE-EXISTING-METRICS" not in result.output
    assert calls == []
    assert metrics.read_bytes() == initial_bytes


def test_direct_measurement_context_keeps_file_exists_compatibility(tmp_path):
    metrics = tmp_path / "already.json"
    metrics.write_bytes(b"UNCHANGED-SECRET")
    with pytest.raises(MeasurementArtifactExistsError) as exc:
        with measurement_artifact(metrics, run_id="run-1", stage="start"):
            raise AssertionError("must never enter capture")
    assert isinstance(exc.value, FileExistsError)
    assert str(metrics) not in str(exc.value)
    assert metrics.read_bytes() == b"UNCHANGED-SECRET"


def test_stage_internal_file_exists_is_not_misreported_as_telemetry_collision(
    tmp_path, monkeypatch
):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    metrics = tmp_path / "new-artifact.json"

    def stage_raises_file_exists(*args, **kwargs):
        raise FileExistsError("unrelated stage error")

    monkeypatch.setattr("projectctl.cli.m11.start_prepared_run", stage_raises_file_exists)
    result = CliRunner().invoke(
        app, ["run", "start", run_id, "--project", str(repo),
              "--measurements", str(metrics)]
    )
    assert result.exit_code != 0
    assert "Measurement artifact already exists" not in result.output
    assert isinstance(result.exception, FileExistsError)
    assert json.loads(metrics.read_text())["state"] == "interrupted_or_error"
