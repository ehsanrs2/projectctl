"""Offline-only negative and positive tests for D2 CTL one-shot PREPARE.

These tests NEVER invoke ProjectCTL prepare/start or model inference.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.dogfooding.d2 import d2_ctl_prepare_once as h


def dummy_plan(target="main"):
    return {
        "task_id": h.TASK, "base_commit": h.POLICY_HEAD,
        "strategy": "direct", "integration_target_ref": target,
        "worker": {"provider": "codex", "actual_model": h.MODEL,
                   "reasoning": "medium"},
        "execution_policy": {
            "sandbox": "workspace_write", "approval": "deny_all",
            "network": "disabled",
            "git": {"commit": False, "branch": False, "merge": False,
                    "push": False},
        },
    }


def dummy_run(rid="run-d2frozen"):
    return {"run_id":rid, "task_id":h.TASK, "status":"claimed",
            "candidate_commit":None, "started_at":None,
            "lease_owner":None, "worktree_id":rid}


class D2CtlPrepareOfflineTests(unittest.TestCase):
    def test_preview_success_never_calls_prepare(self):
        result = {"decision":"D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"}
        with patch.object(sys,"argv",["d2_ctl_prepare_once","--preview"]), (
             patch.object(h,"preview",return_value=result)), (
             patch.object(h,"perform_prepare",
                          side_effect=AssertionError("Forbidden prepare call"))), (
             redirect_stdout(io.StringIO())) as output:
            self.assertEqual(h.main(),0)
        self.assertIn("NO_CLAIM_NO_INFERENCE", output.getvalue())

    def test_prepare_explicit_ack_required(self):
        with patch.object(sys,"argv",["d2_ctl_prepare_once","--prepare"]), (
             patch.object(h,"preview",
                          side_effect=AssertionError("Preview must not run"))), (
             patch.object(h,"perform_prepare",
                          side_effect=AssertionError("Prepare must not run"))), (
             redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as caught:
                h.main()
        self.assertEqual(caught.exception.code,2)

    def test_preview_must_not_contain_ack(self):
        with patch.object(sys,"argv",["d2_ctl_prepare_once","--preview","--ack-claim"]), (
             redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as caught:
                h.main()
        self.assertEqual(caught.exception.code,2)

    def test_quota_probe_not_in_preview(self):
        valid={"decision":"D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED",
               "ctl_run_count":0,"beads_task":"open_unclaimed"}
        def fake_git(repo,*args):
            if args[0]=="branch":
                return "main"
            if args[0]=="rev-parse":
                return h.POLICY_HEAD
            return ""
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(h.os.environ,{"PROJECTCTL_HOME":str(h.ROOT/"ctl-home"),
                                          "BD_ACTOR":"d2-dogfood-owner"}), (
                 patch.object(h,"VENV",Path(sys.executable).parent.parent)), (
                 patch.object(h,"readiness_audit",return_value=valid)), (
                 patch.object(h,"git",side_effect=fake_git)), (
                 patch.object(h,"run_read",
                              side_effect=AssertionError("Quota refresh forbidden in preview"))), (
                 patch.object(h,"OUT",Path(td)/"not-created")):
                expected = h.preview()
        self.assertEqual(expected["decision"],
                         "D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE")
        self.assertFalse(expected["beads_task_claimed"])

    def test_duplicate_evidence_directory_refused_before_audit(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(h,"OUT",Path(td)), (
                 patch.object(h,"readiness_audit",
                              side_effect=AssertionError("must not audit again"))), (
                 patch.dict(h.os.environ,{"PROJECTCTL_HOME":str(h.ROOT/"ctl-home"),
                                           "BD_ACTOR":"d2-dogfood-owner"})), (
                 patch.object(h,"VENV",Path(sys.executable).parent.parent)):
                with self.assertRaisesRegex(ValueError,"NO RETRY"):
                    h.preview()

    def test_one_canonical_task_required(self):
        with self.assertRaisesRegex(ValueError,"exactly one"):
            h.parse_task([{"id":h.TASK},{"id":h.TASK}])
        self.assertEqual(h.parse_task([{"id":h.TASK}])["id"],h.TASK)

    def test_prepared_policy_positive_with_isolated_fake_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            rid="run-d2frozen"
            wt=root/"ctl-home"/"worktrees"/rid
            wt.mkdir(parents=True)
            ctl=root/"fixtures"/"ctl"
            (ctl/".projectctl"/"runs"/rid).mkdir(parents=True)
            (ctl/".projectctl"/"runs"/rid/"execution-plan.json").write_text("{}\n")
            def frozen_git(path, *args):
                if args[0] == "rev-parse":
                    return h.BASE if path == h.DIRECT else h.POLICY_HEAD
                return ""
            with patch.object(h,"ROOT",root),patch.object(h,"CTL",ctl), (
                 patch.object(h,"git",side_effect=frozen_git)):
                got=h.check_preparation(dummy_plan(),dummy_run(),
                    {"id":rid,"path":str(wt),"base_commit":h.POLICY_HEAD},
                    target="main")
            self.assertEqual(got["status"],"claimed")
            self.assertFalse(got["worker_started"])

    def test_prepare_wrong_model_refused(self):
        p=dummy_plan()
        p["worker"]["actual_model"]="other"
        with self.assertRaisesRegex(ValueError,"model/effort"):
            h.check_preparation(p,dummy_run(),{},target="main")

    def test_prepare_wrong_network_refused(self):
        p=dummy_plan()
        p["execution_policy"]["network"]="enabled"
        with self.assertRaisesRegex(ValueError,"sandbox/approval/network"):
            h.check_preparation(p,dummy_run(),{},target="main")

    def test_prepare_privileged_git_refused(self):
        p=dummy_plan()
        p["execution_policy"]["git"]["commit"]=True
        with self.assertRaisesRegex(ValueError,"Git privilege"):
            h.check_preparation(p,dummy_run(),{},target="main")

    def test_prepare_start_time_not_null_refused(self):
        rn=dummy_run()
        rn["started_at"]="2026-10-21T06:00:00Z"
        with self.assertRaisesRegex(ValueError,"Worker appears"):
            h.check_preparation(dummy_plan(),rn,{},target="main")

    def test_prepare_wrong_task_refused(self):
        p=dummy_plan()
        p["task_id"]="unrelated"
        with self.assertRaisesRegex(ValueError,"task is not frozen"):
            h.check_preparation(p,dummy_run(),{},target="main")

    def test_prepare_wrong_base_refused(self):
        p=dummy_plan()
        p["base_commit"]=h.BASE
        with self.assertRaisesRegex(ValueError,"strategy/base"):
            h.check_preparation(p,dummy_run(),{},target="main")

    def test_prepare_wrong_target_refused(self):
        with self.assertRaisesRegex(ValueError,"integration target"):
            h.check_preparation(dummy_plan("other"),dummy_run(),{},target="main")

    def test_failed_offline_quota_never_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"attempt"
            with patch.object(h,"OUT",out),patch.object(h,"run_read",
                 side_effect=RuntimeError("Official quota refused")), (
                 patch.object(h,"readiness_audit",
                              side_effect=AssertionError("should not recheck"))), (
                 patch.object(h.subprocess,"run",
                              side_effect=AssertionError("paid/prepare command forbidden"))):
                data,dispatched=h.perform_prepare({"readiness":"valid",
                                                   "target":"main"})
                self.assertFalse(dispatched)
                self.assertEqual(data["decision"],
                                 "D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY")
                self.assertTrue((out/"prepare-summary.json").is_file())


if __name__=="__main__":
    unittest.main()
