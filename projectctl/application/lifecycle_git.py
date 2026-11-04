"""Bounded, non-mutating Git checks over a stored Run's workspace contract."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from projectctl.core.errors import WorktreeError
from projectctl.core.digest import digest
from projectctl.git import WorktreeManager
from projectctl.project.bootstrap import projectctl_home
from projectctl.trace.snapshot import _FILE_FLAGS, _read_fd, TraceSnapshotError


def _git(root, *args):
    result = subprocess.run(
        ["git", "--no-optional-locks", "--no-pager", "-c", "core.fsmonitor=false",
         "-c", "core.untrackedCache=false", "-C", str(root), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False,
    )
    if result.returncode or len(result.stdout) > 32 * 1024 * 1024:
        raise ValueError("git_observation_unavailable")
    return result.stdout


def porcelain_clean(raw: bytes) -> bool:
    """Never strip leading status blanks (e.g. b' M file\\0')."""
    return raw == b""


def _workspace_digest(worktree, head):
    """Observe execution._worktree_state_digest's contract without runtime IO.

    Use the same HEAD/diff/untracked encoding, with optional Git writes and
    external diff helpers disabled. Unsupported/oversized reads stay unknown.
    """
    patch = _git(worktree, "diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD")
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard", "-z")
    entries = []
    if len(untracked.split(b"\0")) > 512:
        raise ValueError
    for raw in untracked.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = worktree / relative
        if Path(relative).is_absolute() or not path.parent.resolve().is_relative_to(worktree.resolve()):
            raise ValueError
        if path.is_symlink():
            payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            kind = "symlink"
        else:
            fd = os.open(path, _FILE_FLAGS)
            try:
                payload = _read_fd(fd, limit=2 * 1024 * 1024)
            finally:
                os.close(fd)
            kind = "file"
        entries.append({"path": relative, "kind": kind,
                        "sha256": hashlib.sha256(payload).hexdigest()})
    return digest({"head": head, "diff_sha256": hashlib.sha256(patch).hexdigest(),
                   "untracked": sorted(entries, key=lambda item: item["path"])})


def inspect_git(root, db, plan, evidence, integration, checkpoint=None):
    checks = {}

    def set_check(name, state, reason):
        checks[name] = {"state": state, "reason": reason}

    record = db.record
    try:
        if not db.instance_id:
            raise ValueError
        expected = WorktreeManager.storage_path(
            projectctl_home(), db.instance_id, record["worktree_id"])
        if expected != Path(record["worktree_path"]).resolve():
            set_check("worktree_path", "inconsistent", "stored_worktree_path_contract_mismatch")
            return checks
        if expected.is_relative_to(Path(root).resolve()):
            raise ValueError
        set_check("worktree_path", "observed", "stored_identity_manager_path_match")
        if not expected.exists():
            cleaned = integration is not None and integration.worktree_cleaned
            set_check("worktree", "not_applicable" if cleaned else "missing",
                      "post_integration_cleanup" if cleaned else "worktree_missing")
        else:
            head = _git(expected, "rev-parse", "--verify", "HEAD^{commit}").decode().rstrip("\n")
            candidate = record.get("candidate_commit")
            frozen_worker = db.observed_status.value == "claimed" or (
                db.observed_status.value == "running" and record.get("checkpoint_ref"))
            frozen_head = frozen_worker or (
                db.observed_status.value == "verifying" and not candidate)
            wanted_head = record["base_commit"] if frozen_head else candidate
            if wanted_head:
                set_check("worktree_head", "observed" if head == wanted_head else "inconsistent",
                          "frozen_base_head_cross_check" if frozen_head else "candidate_head_cross_check")
            if frozen_worker and record.get("checkpoint_ref"):
                if checkpoint is None or not getattr(checkpoint, "workspace_digest", None):
                    set_check("checkpoint_workspace", "unknown", "checkpoint_workspace_digest_unavailable")
                else:
                    actual = _workspace_digest(expected, head)
                    set_check("checkpoint_workspace", "observed" if actual == checkpoint.workspace_digest
                              else "inconsistent", "checkpoint_workspace_digest_cross_check")
            clean = porcelain_clean(_git(expected, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
            pending_verification = not candidate and db.observed_status.value in {"running", "verifying"}
            # Expected worker changes are not evidence of a clean workspace.
            set_check("worktree_clean", "observed" if clean else
                      "not_applicable" if pending_verification else "inconsistent",
                      "dirty_workspace_pending_verification" if not clean and pending_verification
                      else "git_porcelain_observation")
            set_check("worktree", "observed", "stored_worktree_exists")
        if plan:
            target = _git(root, "rev-parse", "--verify", "--end-of-options",
                          plan.integration_target_ref + "^{commit}").decode().rstrip("\n")
            wanted = integration.target_after if integration else record["base_commit"]
            set_check("target_ref", "observed" if target == wanted else "inconsistent",
                      "target_advanced_or_matches_recorded_boundary")
        candidate = record.get("candidate_commit")
        base = record["base_commit"]
        if candidate and evidence:
            if not all(re.fullmatch(r"[a-fA-F0-9]{7,64}", x) for x in (candidate, base)):
                raise ValueError
            patch = _git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv",
                         "--full-index", base, candidate, "--")
            actual = "sha256:" + hashlib.sha256(patch).hexdigest()
            set_check("candidate_diff", "observed" if actual == evidence.diff_digest else "inconsistent",
                      "committed_diff_digest_cross_check")
    except (OSError, ValueError, KeyError, WorktreeError, TraceSnapshotError, subprocess.TimeoutExpired):
        set_check("git_observation", "unknown", "git_or_worktree_identity_unavailable")
    return checks
