"""G7 test-only epoch oracle versus self-attesting digest inventory.

No producer, key, custodian, runtime schema or source admission is introduced.
The 'external' anchor is an independent *test fixture input*, not a real trust
root. Actual G5/G4 continues to report UNATTESTED for every input pair.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from scripts import m6a_g4_stdin_preview as g4
from scripts import m6a_g5_detached_lab_handoff as g5
from scripts.bdiag_detached_input_lab import PROJECT, RUN
from test_m60m6a_g6_epoch_mixing import _detached_pair, _epoch_bytes

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "O_NOATIME")
    or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="G7 requires disposable fixture files under ordinary Linux user",
)


def _digest_pair(pair):
    # Test-only calculation over exact raw DB and Context bytes.
    assert len(pair) == 2 and all(type(x) is bytes for x in pair)
    return tuple(hashlib.sha256(x).hexdigest() for x in pair)


def _pinned_oracle(epochs):
    # An independent caller retains these digests BEFORE consuming a candidate.
    # Neither G5 nor G4 receives this table or an epoch assertion.
    return {epoch: _digest_pair(pair) for epoch, pair in epochs.items()}


def _matches(anchor, supplied):
    return _digest_pair(supplied) == anchor


def _actual_private_preview(tmp_path, supplied):
    root = _detached_pair(tmp_path, *supplied)
    wire = g5.synthetic_detached_to_g4_wire(
        root, project_id=PROJECT, run_id=RUN
    )
    result = json.loads(g4.render_supplied_wire(wire))
    assert result["source_origin"] == "UNATTESTED"
    assert result["cross_store_epoch"] == "UNATTESTED"
    assert result["source_current"] == "UNKNOWN"
    assert result["assessment_authority"] == "NONE"
    assert result["authorizes_export_cli"] is False
    assert result["trace"]["assessments"] == []
    assert result["trace"]["completeness"] == "incomplete"
    return root, wire, result


@pytest.mark.parametrize(
    ("db_epoch", "context_epoch"),
    [("A", "A"), ("B", "B"), ("A", "B"), ("B", "A")],
    ids=["coherent-a", "coherent-b", "mixed-a-b", "mixed-b-a"],
)
def test_pinned_fixture_oracle_distinguishes_mixed_pairs(
    tmp_path, db_epoch, context_epoch
):
    epochs = _epoch_bytes(tmp_path)
    anchors = _pinned_oracle(epochs)
    supplied = (epochs[db_epoch][0], epochs[context_epoch][1])
    observed = {epoch for epoch, anchor in anchors.items()
                if _matches(anchor, supplied)}
    expected = {db_epoch} if db_epoch == context_epoch else set()
    assert observed == expected
    _, _, preview = _actual_private_preview(tmp_path / "consumer", supplied)
    assert preview["cross_store_epoch"] == "UNATTESTED"


@pytest.mark.parametrize("epoch", ["A", "B"])
def test_wrong_pinned_epoch_refuses_even_coherent_pair(tmp_path, epoch):
    epochs = _epoch_bytes(tmp_path)
    anchors = _pinned_oracle(epochs)
    other = "B" if epoch == "A" else "A"
    assert _matches(anchors[epoch], epochs[epoch])
    assert not _matches(anchors[other], epochs[epoch])


@pytest.mark.parametrize(("db_epoch", "context_epoch"), [("A", "B"), ("B", "A")])
def test_same_actor_self_resigning_never_proves_epoch(
    tmp_path, db_epoch, context_epoch
):
    epochs = _epoch_bytes(tmp_path)
    anchors = _pinned_oracle(epochs)
    mixed = (epochs[db_epoch][0], epochs[context_epoch][1])
    # The same actor who supplies the pair can always recompute valid SHA-256.
    self_attested = _digest_pair(mixed)
    assert _matches(self_attested, mixed)
    assert not any(_matches(anchor, mixed) for anchor in anchors.values())
    _actual_private_preview(tmp_path / "consumer", mixed)


def test_post_acquisition_named_leaf_replacement_breaks_pinned_bytes(tmp_path):
    epochs = _epoch_bytes(tmp_path)
    anchor = _pinned_oracle(epochs)["A"]
    root, old_wire, old_preview = _actual_private_preview(
        tmp_path / "consumer", epochs["A"]
    )
    assert _matches(anchor, epochs["A"])
    new_context = root / g5._CONTEXT
    replacement = root / "test-replacement-only"
    replacement.write_bytes(epochs["B"][1])
    replacement.chmod(0o600)
    os.replace(replacement, new_context)
    now = (epochs["A"][0], new_context.read_bytes())
    assert not _matches(anchor, now)
    # Old G4 wire is still deterministic but cannot speak for current leaves.
    assert json.loads(g4.render_supplied_wire(old_wire)) == old_preview
    assert old_preview["source_current"] == "UNKNOWN"


def test_replacing_untrusted_anchor_can_make_mixed_pair_match(tmp_path):
    epochs = _epoch_bytes(tmp_path)
    anchors = _pinned_oracle(epochs)
    mixed = (epochs["A"][0], epochs["B"][1])
    assert not any(_matches(anchor, mixed) for anchor in anchors.values())
    # This models a compromised/unprotected inventory, NOT key compromise.
    forged_anchor = _digest_pair(mixed)
    assert _matches(forged_anchor, mixed)
    assert forged_anchor not in anchors.values()
    _, _, preview = _actual_private_preview(tmp_path / "consumer", mixed)
    assert preview["cross_store_epoch"] == "UNATTESTED"
