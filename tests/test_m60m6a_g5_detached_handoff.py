"""M6a G5 non-root, synthetic-only detached input handoff regression tests."""
from __future__ import annotations

import base64
import errno
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from scripts import m6a_g5_detached_lab_handoff as g5
from scripts import m6a_g4_stdin_preview as g4
from scripts.m6a_g2_private_byte_diagnostic import G2Refused
from scripts.bdiag_detached_input_lab import PROJECT, RUN
from test_m60m6a_g2_private_byte_diagnostic import _bytes

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "O_NOATIME")
    or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="G5 requires ordinary non-root Linux synthetic fixtures",
)


def _fixture(tmp_path: Path):
    db, files = _bytes(tmp_path)
    root = tmp_path / g5._DIR
    root.mkdir(mode=0o700)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name, raw in (
        (g5._DB, db), (g5._CONTEXT, files["context_manifest"])
    ):
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        os.utime(path, ns=(1_500_000_000_000_000_000,) * 2)
    os.utime(root, ns=(1_500_000_000_000_000_000,) * 2)
    return root, db, files


def _wire(root):
    return g5.synthetic_detached_to_g4_wire(
        root, project_id=PROJECT, run_id=RUN,
    )


def test_deterministic_g5_wire_and_no_observed_metadata_change(tmp_path, capsys):
    root, db, files = _fixture(tmp_path)
    before = g5._observed_metadata(root)
    a, b = _wire(root), _wire(root)
    assert a == b and a.endswith(b"\n")
    assert before == g5._observed_metadata(root)
    assert capsys.readouterr().out == ""
    wire = json.loads(a)
    assert set(wire) == {"format", "project_id", "run_id",
                         "db_b64", "artifacts_b64"}
    assert wire["format"] == g4._INPUT_FORMAT
    assert wire["project_id"] == PROJECT and wire["run_id"] == RUN
    assert base64.b64decode(wire["db_b64"], validate=True) == db
    assert base64.b64decode(
        wire["artifacts_b64"]["context_manifest"], validate=True
    ) == files["context_manifest"]
    assert wire["artifacts_b64"]["verification_manifest"] is None
    assert wire["artifacts_b64"]["evidence_manifest"] is None
    assert g5._HANDOFF_DECISION == "M6A_G5_DETACHED_TEST_HANDOFF_LAB_ONLY"


def test_caller_can_consume_G5_wire_in_G4_after_fixture_removed(tmp_path):
    import shutil
    root, _, _ = _fixture(tmp_path)
    wire = _wire(root)
    shutil.rmtree(root)
    out = json.loads(g4.render_supplied_wire(wire))
    assert out["preview_status"] == "M6A_G4_PREVIEW_LAB_ONLY"
    assert out["source_origin"] == "UNATTESTED"
    assert out["cross_store_epoch"] == "UNATTESTED"
    assert out["source_current"] == "UNKNOWN"
    assert out["assessment_authority"] == "NONE"
    assert out["trace"]["completeness"] == "incomplete"
    assert out["trace"]["assessments"] == []
    assert out["authorizes_export_cli"] is False


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_sidecar_refusal_never_opens_sidecar(tmp_path, monkeypatch, sidecar):
    root, _, _ = _fixture(tmp_path)
    (root / (g5._DB + sidecar)).write_bytes(b"SECRET_SIDE_CAR")
    def no_open(*_args, **_kwargs):
        raise AssertionError("must refuse sidecar without opening any leaf")
    monkeypatch.setattr(os, "open", no_open)
    with pytest.raises(g5.AcquisitionRefused, match="UNSUPPORTED_SQLITE_SIDE_CAR"):
        _wire(root)


@pytest.mark.parametrize("kind", ["missing", "symlink", "hardlink", "fifo"])
def test_unknown_leaf_type_or_alias_refused(tmp_path, kind):
    root, _, _ = _fixture(tmp_path)
    context = root / g5._CONTEXT
    context.unlink()
    if kind == "symlink":
        context.symlink_to(root / g5._DB)
    if kind == "hardlink":
        os.link(root / g5._DB, context)
    if kind == "fifo":
        os.mkfifo(context, mode=0o600)
    with pytest.raises(g5.AcquisitionRefused):
        _wire(root)


def test_no_plain_read_fallback_after_noatime_denial(tmp_path, monkeypatch):
    root, _, _ = _fixture(tmp_path)
    calls = []
    def deny_noatime(path, flags, *args, **kwargs):
        calls.append(flags)
        if flags & os.O_NOATIME:
            raise OSError(errno.EPERM, "NOATIME unavailable")
        raise AssertionError("unsafe fallback open")
    monkeypatch.setattr(os, "open", deny_noatime)
    with pytest.raises(g5.AcquisitionRefused, match="NOATIME_OR_FILE_ACCESS_DENIED"):
        _wire(root)
    assert calls and all(flags & os.O_NOATIME for flags in calls)


def test_second_read_mutating_first_leaf_is_detected(tmp_path, monkeypatch):
    root, _, _ = _fixture(tmp_path)
    real_read = os.read
    seen = []
    def mutate_after_first_leaf(fd, length):
        raw = real_read(fd, length)
        seen.append(True)
        # First leaf typically takes one read plus EOF; third read is
        # the first read of the context leaf. Local injected mutation only.
        if len(seen) == 3:
            os.utime(root / g5._DB, ns=(1_650_000_000_000_000_000,) * 2)
        return raw
    monkeypatch.setattr(os, "read", mutate_after_first_leaf)
    with pytest.raises(g5.AcquisitionRefused, match="DETACHED_CROSS_READ_CHANGE"):
        _wire(root)


def test_unknown_root_and_root_symlink_refused(tmp_path):
    root, _, _ = _fixture(tmp_path)
    wrong = tmp_path / "wrong-root"
    wrong.mkdir(mode=0o700)
    with pytest.raises(g5.AcquisitionRefused, match="OUTSIDE_G5_LAB_INPUT_SCOPE"):
        _wire(wrong)
    parent = tmp_path / "alias"
    parent.mkdir(mode=0o700)
    alias = parent / g5._DIR
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(g5.AcquisitionRefused):
        _wire(alias)


def test_bad_run_id_does_not_create_valid_G4_source(tmp_path):
    root, _, _ = _fixture(tmp_path)
    wire = g5.synthetic_detached_to_g4_wire(
        root, project_id=PROJECT, run_id="other-run-id"
    )
    with pytest.raises((G2Refused, g4.G4Refused)):
        g4.render_supplied_wire(wire)


def test_wal_header_is_not_recovered(tmp_path):
    root, _, _ = _fixture(tmp_path)
    db = root / g5._DB
    raw = bytearray(db.read_bytes())
    raw[18:20] = b"\x02\x02"
    db.write_bytes(raw)
    wire = _wire(root)
    with pytest.raises(G2Refused, match="UNSUPPORTED_WAL_INPUT"):
        g4.render_supplied_wire(wire)


def test_no_main_public_cli_or_original_source_path_writes():
    import inspect
    assert set(inspect.signature(g5.synthetic_detached_to_g4_wire).parameters) == {
        "root", "project_id", "run_id",
    }
    source = Path(g5.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess.", "requests.", "httpx.", "socket.",
                      "argparse.", "Typer(", "click.", "print(",
                      "RunStore(", "connect_db(", "write_bytes("):
        assert forbidden not in source
