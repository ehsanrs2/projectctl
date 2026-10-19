"""M0x bounded nonroot fixture: real SIGKILL and every inner deletion window."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from scripts import m0x_anchored_crash_window_lab as m0x


def _ordinary() -> bool:
    return sys.platform == "linux" and os.getuid() != 0 and os.geteuid() != 0


def _prepared(tmp_path: Path) -> Path:
    return m0x.prepare_private(tmp_path)


def _assert_quarantined(root: Path, base: Path, expected: str) -> None:
    with pytest.raises(m0x.Refused, match=expected):
        m0x.reconcile_private(root, base)
    assert root.exists()


def test_real_four_sigkill_windows_and_fresh_interpreter_replays():
    if not _ordinary():
        pytest.skip("Linux nonroot only")
    result = m0x.exercise()
    assert result["decision"] == "NO_GO_PRIVATE_CRASH_WINDOWS_REPLAYED"
    assert result["crash_points_verified"] == list(m0x._PHASES)
    assert result["fresh_recovery_processes"] == 4
    assert result["fixture_absent_after_harness_teardown"] is True
    for key in m0x._CEILING:
        assert result[key] is False


@pytest.mark.parametrize("phase", m0x._PHASES)
def test_each_exact_crash_window_can_reconcile_from_outer_anchor(tmp_path, phase):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    m0x.apply_private_phase(root, tmp_path, phase)
    if phase == "after_journal_unlink":
        assert (root / m0x._WORK).is_dir()
        assert list((root / m0x._WORK).iterdir()) == []
        assert (root / m0x._ANCHOR).is_file()
    if phase == "after_work_rmdir":
        assert not (root / m0x._WORK).exists()
        assert (root / m0x._ANCHOR).is_file()
    result = m0x.reconcile_private(root, tmp_path)
    assert result["decision"] == "NO_GO_ANCHORED_PRIVATE_REPLAY_OBSERVED"
    assert result["outer_anchor_preserved"] is True
    assert result["work_absent"] is True
    # This only makes the *private inner transaction* replayable, not
    # the separate post-test teardown of the last remaining anchor.
    assert (root / m0x._ANCHOR).is_file()
    m0x.retire_fixture(root, tmp_path)
    assert not root.exists()


def test_inner_recovery_is_idempotent_until_harness_retires_anchor(tmp_path):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    first = m0x.reconcile_private(root, tmp_path)
    second = m0x.reconcile_private(root, tmp_path)
    assert first == second
    assert list(root.iterdir()) == [root / m0x._ANCHOR]
    m0x.retire_fixture(root, tmp_path)


def test_root_anchor_is_fsynced_before_work_scope_published(tmp_path, monkeypatch):
    if not _ordinary():
        pytest.skip("nonroot only")
    saw = []
    original = m0x._publish
    def record(path, name, data):
        saw.append((path.name, name))
        return original(path, name, data)
    monkeypatch.setattr(m0x, "_publish", record)
    root = _prepared(tmp_path)
    assert saw[0] == (root.name, m0x._ANCHOR)
    assert saw[1] == ("work", m0x._JOURNAL)
    assert saw[2] == ("work", m0x._EFFECT)
    m0x.reconcile_private(root, tmp_path)
    m0x.retire_fixture(root, tmp_path)


@pytest.mark.parametrize("tamper", [
    "alter_anchor", "missing_anchor", "anchor_symlink", "anchor_hardlink",
    "unknown_root_leaf", "wrong_anchor_mode", "wrong_root_mode",
])
def test_untrusted_outer_anchor_and_scope_always_quarantined(tmp_path, tamper):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    anchor = root / m0x._ANCHOR
    if tamper == "alter_anchor":
        anchor.write_bytes(b"wrong anchor")
    elif tamper == "missing_anchor":
        anchor.unlink()
    elif tamper == "anchor_symlink":
        target = tmp_path / "external-no-delete"
        target.write_bytes(anchor.read_bytes())
        anchor.unlink()
        anchor.symlink_to(target)
    elif tamper == "anchor_hardlink":
        os.link(anchor, tmp_path / "external-hardlink")
    elif tamper == "unknown_root_leaf":
        (root / "foreign").write_text("do not touch")
    elif tamper == "wrong_anchor_mode":
        anchor.chmod(0o644)
    else:
        root.chmod(0o755)
    with pytest.raises(m0x.Refused):
        m0x.reconcile_private(root, tmp_path)
    assert root.exists()
    assert (root / m0x._WORK / m0x._JOURNAL).exists()


@pytest.mark.parametrize("tamper", [
    "journal_corrupt", "effect_corrupt", "effect_without_journal",
    "effect_symlink", "journal_hardlink", "unknown_work_leaf",
    "work_symlink", "work_bad_mode", "effect_bad_mode",
])
def test_unexpected_inner_state_never_destructively_replays(tmp_path, tamper):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    work = root / m0x._WORK
    journal = work / m0x._JOURNAL
    effect = work / m0x._EFFECT
    if tamper == "journal_corrupt":
        journal.write_bytes(b"wrong")
    elif tamper == "effect_corrupt":
        effect.write_bytes(b"tampered")
    elif tamper == "effect_without_journal":
        journal.unlink()
    elif tamper == "effect_symlink":
        data = tmp_path / "outside"
        data.write_bytes(m0x._PAYLOAD)
        effect.unlink()
        effect.symlink_to(data)
    elif tamper == "journal_hardlink":
        os.link(journal, tmp_path / "outside")
    elif tamper == "unknown_work_leaf":
        (work / "foreign").write_text("no")
    elif tamper == "work_symlink":
        alternative = tmp_path / "work-other"
        alternative.mkdir()
        # rename the actual work to preserve its files and replace with a symlink.
        work.rename(tmp_path / "preserved-work")
        work.symlink_to(alternative, target_is_directory=True)
    elif tamper == "work_bad_mode":
        work.chmod(0o755)
    elif tamper == "effect_bad_mode":
        effect.chmod(0o644)
    with pytest.raises(m0x.Refused):
        m0x.reconcile_private(root, tmp_path)
    assert root.exists()
    assert (root / m0x._ANCHOR).exists()


def test_no_delete_after_arbitrary_out_of_scope_path(tmp_path):
    if not _ordinary():
        pytest.skip("nonroot only")
    ordinary = tmp_path / "actual-project"
    ordinary.mkdir()
    with pytest.raises(m0x.Refused, match="OUTSIDE_FIXED_NONROOT_FIXTURE"):
        m0x.reconcile_private(ordinary, tmp_path)
    assert ordinary.is_dir()


def test_extra_work_directory_fails_safe(tmp_path):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    (root / m0x._WORK / "unexpected-dir").mkdir()
    _assert_quarantined(root, tmp_path, "QUARANTINE_UNKNOWN_WORK_LEAF")


def test_premature_retirement_refuses(tmp_path):
    if not _ordinary():
        pytest.skip("nonroot only")
    root = _prepared(tmp_path)
    with pytest.raises(m0x.Refused, match="UNFINISHED_WORK_PREVENTS_TEARDOWN"):
        m0x.retire_fixture(root, tmp_path)
    assert (root / m0x._ANCHOR).exists()


def test_nonroot_required_before_any_fixture_create(tmp_path, monkeypatch):
    monkeypatch.setattr(m0x.os, "geteuid", lambda: 0)
    with pytest.raises(m0x.Refused, match="NONROOT_LINUX_REQUIRED"):
        m0x.prepare_private(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_inspect_does_not_call_mutating_exercise(monkeypatch, capsys):
    monkeypatch.setattr(m0x, "exercise", lambda: pytest.fail("must not exercise"))
    assert m0x.main(["--inspect"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "NO_GO_RECOVERY_EXERCISE_NOT_RUN"
    assert data["authorizes_policy_install"] is False


def test_exercise_requires_exact_ack(monkeypatch, capsys):
    monkeypatch.setattr(m0x, "exercise", lambda: pytest.fail("ack missing"))
    assert m0x.main(["--exercise"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "NO_GO_EXPLICIT_NONROOT_ACK_REQUIRED"


@pytest.mark.parametrize("args", [
    [], ["--run"], ["--install"], ["--load-profile"], ["--reboot"],
    ["--source", "/home/old-project"], ["--exercise", "--output", "/etc"],
    ["--inspect", "--exercise"], ["--internal-phase", "not_a_stage"],
    ["--internal-root", "/tmp/something", "--exercise"],
])
def test_refuse_root_or_caller_supplied_external_action(args):
    with pytest.raises(SystemExit) as err:
        m0x.main(args)
    assert err.value.code != 0


def test_internal_recovery_rejects_foreign_directory_without_touching_it(tmp_path):
    if not _ordinary():
        pytest.skip("nonroot only")
    foreign = tmp_path / "important-data"
    foreign.mkdir()
    assert m0x._fresh_recovery_worker(foreign) == 1
    assert foreign.exists()


def test_no_systemd_apparmor_or_real_project_actions():
    body = Path(m0x.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "apparmor_parser -r", "apparmor_parser -a", "systemctl start",
        "systemctl enable", "/etc/apparmor.d/", "/etc/systemd/system/",
        "os.chown(", "os.setuid(", "os.setgroups(", "shutil.rmtree(",
        "os.kill(",
    ):
        assert forbidden not in body
