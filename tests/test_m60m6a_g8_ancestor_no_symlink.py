"""G8: nonroot, disposable no-symlink ancestor path regression.

No real RunStore access; only G5 synthetic test-owned rollback images. The
descriptor walk protects against following *observed path-component symlinks*,
not same-UID hostile directory replacement, bind mounts or source provenance.
"""
from __future__ import annotations

import os
import sys

import pytest

from scripts import m6a_g4_stdin_preview as g4
from scripts import m6a_g5_detached_lab_handoff as g5
from scripts.bdiag_detached_input_lab import PROJECT, RUN
from test_m60m6a_g5_detached_handoff import _fixture

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not all(
        hasattr(os, flag) for flag in ("O_PATH", "O_NOATIME", "O_NOFOLLOW")
    ) or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="G8 must execute as an ordinary nonroot Linux user",
)


def _wire(root):
    return g5.synthetic_detached_to_g4_wire(
        root, project_id=PROJECT, run_id=RUN,
    )


def test_nested_real_ancestors_still_allow_synthetic_preview(tmp_path):
    root, _, _ = _fixture(tmp_path / "real" / "nested")
    wire = _wire(root)
    preview = __import__("json").loads(g4.render_supplied_wire(wire))
    assert preview["cross_store_epoch"] == "UNATTESTED"
    assert preview["source_current"] == "UNKNOWN"
    assert preview["trace"]["assessments"] == []


@pytest.mark.parametrize("location", ["early", "late"])
def test_symlinked_ancestor_refuses_before_any_leaf_open(
    tmp_path, monkeypatch, location
):
    parent = tmp_path / "real-parent"
    root, _, _ = _fixture(parent)
    if location == "early":
        alias = tmp_path / "redirect"
        alias.symlink_to(parent, target_is_directory=True)
    else:
        outer = tmp_path / "ordinary"
        outer.mkdir()
        alias = outer / "redirect"
        alias.symlink_to(parent, target_is_directory=True)
    alias_root = alias / g5._DIR
    assert root != alias_root

    real_open = os.open
    visited = []

    def observe(path, flags, *args, **kwargs):
        if path in (g5._DB, g5._CONTEXT):
            raise AssertionError("no synthetic leaf may be opened after alias")
        visited.append((path, flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", observe)
    with pytest.raises(
        g5.AcquisitionRefused, match="^UNTRUSTED_DETACHED_DIRECTORY_CHAIN$"
    ):
        _wire(alias_root)
    assert visited and visited[0][0] == "/"
    assert any(path == "redirect" for path, _ in visited)
    assert all(flags & os.O_NOFOLLOW for _, flags in visited)
    assert all(flags & os.O_PATH for _, flags in visited)


def test_dotdot_path_is_refused_even_if_it_resolves_to_owned_root(
    tmp_path, monkeypatch
):
    _fixture(tmp_path)
    (tmp_path / "intermediate").mkdir()
    noncanonical = tmp_path / "intermediate" / ".." / g5._DIR
    assert ".." in noncanonical.parts
    real_open = os.open

    def observe(path, flags, *args, **kwargs):
        if path in (g5._DB, g5._CONTEXT):
            raise AssertionError("no leaf open for noncanonical scope")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", observe)
    with pytest.raises(
        g5.AcquisitionRefused, match="^UNTRUSTED_DETACHED_DIRECTORY_CHAIN$"
    ):
        _wire(noncanonical)


def test_missing_o_path_support_fails_closed_without_leaf_open(
    tmp_path, monkeypatch
):
    root, _, _ = _fixture(tmp_path)
    monkeypatch.delattr(os, "O_PATH", raising=False)
    with pytest.raises(
        g5.AcquisitionRefused, match="^UNTRUSTED_DETACHED_DIRECTORY_CHAIN$"
    ):
        _wire(root)
