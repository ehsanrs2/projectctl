"""G6: falsifiable synthetic cross-store epoch controls; no source authority.

The test-only oracle knows fixture provenance. G5/G4 never receives that oracle.
All SQLite files and external leaves are disposable, owned by pytest tmp_path.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys

import pytest

from scripts import m6a_g4_stdin_preview as g4
from scripts import m6a_g5_detached_lab_handoff as g5
from scripts.bdiag_detached_input_lab import PROJECT, RUN
from test_m60m6a_g5_detached_handoff import _fixture

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "O_NOATIME")
    or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="G6 requires synthetic fixtures under an ordinary Linux user",
)


def _epoch_bytes(tmp_path):
    """Independently create A and B using real G2-compatible test fixtures."""
    root_a, db_a, files_a = _fixture(tmp_path / "epoch-a")
    root_b, _, _ = _fixture(tmp_path / "epoch-b")
    # B is a genuine separately committed SQLite revision, not a forged Trace.
    db_b_path = root_b / g5._DB
    with sqlite3.connect(db_b_path) as conn:
        conn.execute(
            "UPDATE run_events SET event_type=? WHERE run_id=?",
            ("worker.changed_epoch_b", RUN),
        )
        conn.commit()
    db_b = db_b_path.read_bytes()
    assert db_a != db_b
    assert db_a[18:20] == db_b[18:20] == b"\x01\x01"

    context_a = files_a["context_manifest"]
    context_b_path = root_b / g5._CONTEXT
    context_b_model = json.loads(context_b_path.read_bytes())
    # This valid context has the same task identity but a distinct generation
    # revision. The real ContextManifest has no common DB epoch identifier.
    context_b_model["git_commit"] = "cafebabe"
    context_b = json.dumps(
        context_b_model, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert json.loads(context_a)["git_commit"] != "cafebabe"
    assert context_a != context_b
    return {"A": (db_a, context_a), "B": (db_b, context_b)}


def _detached_pair(tmp_path, db, context):
    # Only fixed synthetic G5 leaf names; no actual project paths.
    root = tmp_path / g5._DIR
    root.mkdir(mode=0o700)
    for name, raw in ((g5._DB, db), (g5._CONTEXT, context)):
        leaf = root / name
        leaf.write_bytes(raw)
        leaf.chmod(0o600)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    return root


def _preview(root):
    wire = g5.synthetic_detached_to_g4_wire(
        root, project_id=PROJECT, run_id=RUN,
    )
    return wire, json.loads(g4.render_supplied_wire(wire))


@pytest.mark.parametrize(
    ("db_epoch", "context_epoch"),
    [("A", "A"), ("B", "B"), ("A", "B"), ("B", "A")],
    ids=["coherent-a", "coherent-b", "mixed-db-a-context-b",
         "mixed-db-b-context-a"],
)
def test_private_preview_cannot_prove_mixed_epoch(
    tmp_path, db_epoch, context_epoch,
):
    # External fixture-generation oracle, not an input to G5 or G4.
    epochs = _epoch_bytes(tmp_path)
    root = _detached_pair(
        tmp_path / "case", epochs[db_epoch][0], epochs[context_epoch][1],
    )
    wire, result = _preview(root)
    assert wire.endswith(b"\n")
    assert result["source_origin"] == "UNATTESTED"
    assert result["cross_store_epoch"] == "UNATTESTED"
    assert result["source_current"] == "UNKNOWN"
    assert result["assessment_authority"] == "NONE"
    assert result["authorizes_export_cli"] is False
    assert result["trace"]["assessments"] == []
    assert result["trace"]["completeness"] == "incomplete"
    sources = {item["source_kind"]: item
               for item in result["trace"]["sources"]}
    # "present" means valid format/available identity, not same epoch.
    assert sources["context_manifest"]["validation_state"] == "present"
    assert sources["run_record"]["validation_state"] == "present"
    assert sources["run_event_stream"]["validation_state"] == "present"
    assert (db_epoch == context_epoch) == (
        (db_epoch, context_epoch) in {("A", "A"), ("B", "B")}
    )
    # Mixed fixtures and coherent fixtures share exactly the same *authority*
    # status; a consumer must not interpret 'present' as an epoch certificate.


def test_previous_wire_remains_unattested_after_leaf_replacement(tmp_path):
    epochs = _epoch_bytes(tmp_path)
    root = _detached_pair(tmp_path / "case", *epochs["A"])
    old_wire, old_result = _preview(root)
    # Replace the named context only AFTER G5 has completed acquisition.
    new_context = root / g5._CONTEXT
    replacement = root / "test-owned-replacement"
    replacement.write_bytes(epochs["B"][1])
    replacement.chmod(0o600)
    os.replace(replacement, new_context)
    assert new_context.read_bytes() == epochs["B"][1]
    # G4 only has previously supplied bytes; it has no current-source oracle.
    assert json.loads(g4.render_supplied_wire(old_wire)) == old_result
    _, changed_result = _preview(root)
    assert changed_result["cross_store_epoch"] == "UNATTESTED"
    assert changed_result["source_current"] == "UNKNOWN"
    assert changed_result["trace"]["completeness"] == "incomplete"
    assert changed_result["trace"]["assessments"] == []


def test_mixed_publication_order_is_not_an_atomic_epoch_proof(tmp_path):
    epochs = _epoch_bytes(tmp_path)
    root = _detached_pair(
        tmp_path / "case", epochs["A"][0], epochs["A"][1],
    )
    _, before = _preview(root)
    # Simulate crash after DB B publication, before context B publication.
    db_leaf = root / g5._DB
    db_leaf.write_bytes(epochs["B"][0])
    _, half_published = _preview(root)
    # The second step makes a coherent B pair; all three remain unattested.
    (root / g5._CONTEXT).write_bytes(epochs["B"][1])
    _, after = _preview(root)
    for outcome in (before, half_published, after):
        assert outcome["cross_store_epoch"] == "UNATTESTED"
        assert outcome["source_current"] == "UNKNOWN"
        assert outcome["trace"]["assessments"] == []
    assert half_published["trace"]["completeness"] == "incomplete"
