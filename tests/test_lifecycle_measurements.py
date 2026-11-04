import pytest
import json

from projectctl.telemetry.lifecycle import capture_measurements, measured, observed_sdk_call
from projectctl.telemetry.lifecycle import measurement_artifact
from projectctl.telemetry.lifecycle_reader import inspect_measurements


def test_opt_in_and_monotonic_boundaries(monkeypatch):
    times = iter([10, 15, 30, 50])
    monkeypatch.setattr("projectctl.telemetry.lifecycle.monotonic_ns", lambda: next(times))

    @measured("outer")
    def operation():
        return observed_sdk_call(lambda: "result")

    with capture_measurements() as records:
        assert operation() == "result"
    assert [(r["boundary"], r["duration_ns"]) for r in records] == [
        ("sdk_turn_call", 15), ("outer", 40)]
    assert records[0]["usage"]["scopes"]["total"]["input_tokens"]["state"] == "unknown"
    # Inactive captures must not even call the measurement clock.
    assert operation() == "result"


@pytest.mark.parametrize("exception,outcome", [(ValueError, "error"), (KeyboardInterrupt, "interrupted")])
def test_failure_preserves_exception_and_unknown_usage(exception, outcome):
    def fail():
        raise exception("secret")
    with capture_measurements() as records:
        with pytest.raises(exception):
            observed_sdk_call(fail)
    assert records[0]["outcome"] == outcome
    assert "secret" not in str(records)
    assert records[0]["duration_ns"] >= 0


def test_nested_contexts_do_not_leak():
    with capture_measurements() as outer:
        with capture_measurements() as inner:
            observed_sdk_call(lambda: None)
        observed_sdk_call(lambda: None)
    assert len(outer) == len(inner) == 1


def test_exclusive_artifact_pending_before_operation_and_no_retry(tmp_path):
    path = tmp_path / "metrics.json"
    with measurement_artifact(path, run_id="run-1", stage="start"):
        assert json.loads(path.read_text())["state"] == "pending"
        assert inspect_measurements(path, "run-1")["state"] == "unknown"
        observed_sdk_call(lambda: None)
    before = path.read_bytes()
    assert inspect_measurements(path, "run-1")["state"] == "observed"
    with pytest.raises(FileExistsError):
        with measurement_artifact(path, run_id="run-1", stage="start"):
            pytest.fail("duplicate must never reach operation")
    assert path.read_bytes() == before
    assert inspect_measurements(path, "other")["state"] == "inconsistent"


def test_error_artifact_has_no_exception_payload(tmp_path):
    path = tmp_path / "metrics.json"
    with pytest.raises(RuntimeError):
        with measurement_artifact(path, run_id="run-1", stage="verify"):
            observed_sdk_call(lambda: (_ for _ in ()).throw(RuntimeError("SECRET")))
    assert "SECRET" not in path.read_text()
    assert json.loads(path.read_text())["state"] == "interrupted_or_error"
    assert inspect_measurements(path, "run-1")["state"] == "observed"


@pytest.mark.parametrize("mutation", ["duration", "source", "timestamp", "clock", "version"])
def test_tampered_measurements_are_not_comparison_evidence(tmp_path, mutation):
    path = tmp_path / "metrics.json"
    with measurement_artifact(path, run_id="run-1", stage="start"):
        observed_sdk_call(lambda: None)
    data = json.loads(path.read_text())
    if mutation == "timestamp":
        data["completed_at"] = "1900-01-01T00:00:00+00:00"
    else:
        field, value = {"duration": ("duration_ns", -1), "source": ("source", "SECRET"),
                        "clock": ("clock", "wall"), "version": ("schema_version", 99)}[mutation]
        data["measurements"][0][field] = value
    path.write_text(json.dumps(data))
    assert inspect_measurements(path, "run-1")["state"] == "inconsistent"


def test_fake_adapter_checkpoint_preserves_sdk_attribution(tmp_path):
    from test_m12b_codex_adapter import checkpoint_bindings, request, FakeCheckpointMonitor
    from projectctl.workers.codex.adapter import CodexWorkerAdapter
    with capture_measurements() as records:
        result = CodexWorkerAdapter(bindings_loader=checkpoint_bindings).start(
            request(), workspace=tmp_path, checkpoint_monitor=FakeCheckpointMonitor())
    assert result.schema_kind == "projectctl.worker_checkpoint"
    assert records[0]["boundary"] == "sdk_turn_call"
    assert records[0]["usage"]["scopes"]["last"]["input_tokens"]["state"] == "unknown"


@pytest.mark.parametrize("scope", ["last", "total"])
@pytest.mark.parametrize("subset", ["cached_input_tokens", "reasoning_output_tokens"])
def test_artifact_reader_rejects_inconsistent_subset_observations(tmp_path, scope, subset):
    from types import SimpleNamespace as NS
    counter = NS(input_tokens=10, cached_input_tokens=5, output_tokens=5,
                 reasoning_output_tokens=2, total_tokens=15)
    path = tmp_path / "metrics.json"
    with measurement_artifact(path, run_id="run-1", stage="start"):
        observed_sdk_call(lambda: NS(usage=NS(last=counter, total=counter)))
    assert inspect_measurements(path, "run-1")["state"] == "observed"
    raw = json.loads(path.read_text())
    raw["measurements"][0]["usage"]["scopes"][scope][subset]["value"] = 999
    path.write_text(json.dumps(raw))
    assert inspect_measurements(path, "run-1") == {
        "state": "inconsistent", "reason": "measurement_provenance_invalid"}


def test_capture_and_reader_preserve_unknown_inconsistent_subsets(tmp_path, monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda name: "0.160.0")
    from types import SimpleNamespace as NS
    path = tmp_path / "metrics.json"
    with measurement_artifact(path, run_id="run-1", stage="start"):
        observed_sdk_call(lambda: NS(usage=NS(last=NS(input_tokens=10, cached_input_tokens=999),
                                             total=NS(output_tokens=5, reasoning_output_tokens=100))))
    report = inspect_measurements(path, "run-1")
    assert report["state"] == "observed"
    scopes = report["measurements"][0]["usage"]
    assert scopes["last"]["cached_input_tokens"] == {"state": "unknown", "value": None}
    assert scopes["last"]["input_tokens"]["value"] == 10
    assert scopes["total"]["reasoning_output_tokens"] == {"state": "unknown", "value": None}
    assert scopes["total"]["output_tokens"]["value"] == 5


@pytest.mark.parametrize("sdk_version", ["unknown", "0.159.0"])
def test_reader_keeps_usage_unknown_for_unverified_sdk(tmp_path, monkeypatch, sdk_version):
    monkeypatch.setattr("importlib.metadata.version", lambda name: sdk_version)
    path = tmp_path / "metrics.json"
    with measurement_artifact(path, run_id="run-1", stage="start"):
        observed_sdk_call(lambda: object())
    usage = inspect_measurements(path, "run-1")["measurements"][0]["usage"]
    assert usage == {"state": "unknown", "reason": "sdk_version_not_offline_verified"}
