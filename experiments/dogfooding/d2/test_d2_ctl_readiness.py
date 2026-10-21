"""Pure offline D2 CTL post-Direct readiness gate tests; never claim/start a worker."""
from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

from experiments.dogfooding.d2 import d2_ctl_readiness as check


def valid_result():
    return {
        "decision": "D2_DIRECT_CANDIDATE_EVIDENCE_AUDIT_PASS__SEMANTIC_REVIEW_PENDING",
        "changed_paths": sorted(check.DIRECT_SOURCE),
        "test_count": 26,
        "test_exit_code": 0,
        "direct_head": check.BASE,
        "ctl_head": check.POLICY_HEAD,
        "source_inventory": {
            path: {"sha256": value} for path,value in check.DIRECT_SOURCE.items()
        },
    }


def valid_preflight():
    return {
        "decision": "D2_NO_INFERENCE_PREFLIGHT_PASS",
        "predeclared_order": ["direct_cli", "projectctl"],
    }


def valid_ready():
    return [{"id":"d2ctl-g4q","status":"open"}]


def valid_detail(description: str):
    return [{"id":"d2ctl-g4q","status":"open","assignee":None,
             "description":description}]


class D2CtlReadinessTests(unittest.TestCase):
    def test_policy_digest_constants_are_owned_by_frozen_audit(self):
        # Regression for the original module-import error: POLICY_SHA does
        # not exist in d2_freeze_policy. Reuse the proven frozen audit map.
        from experiments.dogfooding.d2 import d2_post_freeze_audit as frozen
        from experiments.dogfooding.d2 import d2_freeze_policy as freeze
        self.assertEqual(check.POLICY_SHA, frozen.POLICY_SHA)
        self.assertEqual(check.SPEC_SHA, freeze.SPEC_SHA)
        self.assertEqual(set(check.POLICY_SHA), {
            ".gitignore", ".projectctl/config.yaml",
            "projectctl.scope.yaml", "projectctl.verification.yaml",
        })

    def test_matching_finished_direct_snapshot(self):
        check.validate_snapshots(valid_result(),valid_preflight())

    def test_direct_sha_mismatch_is_blocked(self):
        r=valid_result()
        r["source_inventory"]["d2events/cli.py"]["sha256"]="wrong"
        with self.assertRaisesRegex(ValueError,"SHA drift"):
            check.validate_snapshots(r,valid_preflight())

    def test_direct_changed_paths_must_be_exact(self):
        r=valid_result()
        r["changed_paths"] += ["SPEC.md"]
        with self.assertRaisesRegex(ValueError,"Direct frozen result drift"):
            check.validate_snapshots(r,valid_preflight())

    def test_failed_independent_tests_block(self):
        r=valid_result()
        r["test_exit_code"]=1
        with self.assertRaisesRegex(ValueError,"Direct frozen result drift"):
            check.validate_snapshots(r,valid_preflight())

    def test_original_preflight_order_cannot_change(self):
        p=valid_preflight()
        p["predeclared_order"]=["projectctl","direct_cli"]
        with self.assertRaisesRegex(ValueError,"ordering changed"):
            check.validate_snapshots(valid_result(),p)

    def test_unreviewed_direct_evidence_refused(self):
        r=valid_result()
        r["decision"]="D2_DIRECT_TEST_FAILED"
        with self.assertRaisesRegex(ValueError,"Direct evidence"):
            check.validate_snapshots(r,valid_preflight())

    def test_one_ready_unclaimed_beads_task(self):
        with patch.object(check, "CTL", Path("/unused")):
            with patch.object(Path, "read_text", return_value="Frozen SPEC\n"):
                check.validate_task(valid_ready(),valid_detail("Frozen SPEC\n"))

    def test_beads_claimed_refused(self):
        task=valid_detail("Frozen SPEC\n")
        task[0]["assignee"]="other"
        with self.assertRaisesRegex(ValueError,"ready/unclaimed"):
            check.validate_task(valid_ready(),task)

    def test_beads_description_modified_refused(self):
        with patch.object(check,"CTL",Path("/unused")):
            with patch.object(Path,"read_text",return_value="Canonical SPEC"):
                with self.assertRaisesRegex(ValueError,"description differs"):
                    check.validate_task(valid_ready(),valid_detail("CHANGED SPEC"))

    def test_no_readonly_flag_refuses_before_audit(self):
        with patch.object(sys,"argv",["d2_ctl_readiness"]), (
            patch.object(check,"audit",side_effect=AssertionError("must not audit"))), (
            redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as caught:
                check.main()
        self.assertEqual(caught.exception.code,2)

    def test_readonly_flag_prints_only_summary(self):
        with patch.object(sys,"argv",["d2_ctl_readiness","--read-only"]), (
            patch.object(check,"audit",return_value={
                "decision": "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED"
            })), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check.main(),0)
        self.assertIn("CLAIM_NOT_AUTHORIZED",output.getvalue())

    def test_git_preserves_porcelain_marker(self):
        with patch.object(check,"read_command",return_value=" M source.py\n"):
            self.assertEqual(check.git(Path("/unused"),"status","--porcelain")," M source.py")


if __name__ == "__main__":
    unittest.main()
