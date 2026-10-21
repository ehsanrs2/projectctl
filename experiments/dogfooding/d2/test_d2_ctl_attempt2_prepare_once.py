"""D2 Prepare Attempt-2 synthetic safety tests. No provider/model/claim requests."""
from __future__ import annotations
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from experiments.dogfooding.d2 import d2_ctl_attempt2_prepare_once as h


class Attempt2PrepareTests(unittest.TestCase):
    def test_requires_approved_exact_research_head(self):
        with self.assertRaisesRegex(ValueError,"Exact research SHA"):
            h.preview("HEAD")

    def test_existing_attempt_identity_refused_before_read(self):
        with TemporaryDirectory() as td:
            out=Path(td)/"attempt2"
            out.mkdir()
            with patch.object(h,"OUT",out), (
                 patch.object(h.old,"git",
                              side_effect=AssertionError("no reads expected"))):
                with self.assertRaisesRegex(ValueError,"NO RETRY"):
                    h.preview("a"*40)

    def test_missing_offline_record_refused(self):
        with TemporaryDirectory() as td:
            with patch.object(h,"OFFLINE",Path(td)/"absent"):
                with self.assertRaisesRegex(ValueError,"missing"):
                    h.bound_offline_evidence()

    def test_offline_failure_does_not_qualify(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            (root/"result.txt").write_text(
                "decision=D2_ATTEMPT2_OFFLINE_BLOCKED\n"
                "research_commit="+h.QUALIFIED_HEAD+"\n"
                "exit_code=2\n")
            with patch.object(h,"OFFLINE",root):
                with self.assertRaisesRegex(ValueError,"did not pass"):
                    h.bound_offline_evidence()

    def test_invalid_manifest_rejected(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            (root/"result.txt").write_text(
                "decision=D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED\n"
                "research_commit="+h.QUALIFIED_HEAD+"\n"
                "last_step=complete\nexit_code=0\n"
                "attempt2_prepare_dispatched=false\npaid_worker_started=false\n")
            (root/"FILE_SHA256.txt").write_text(
                "0"*64+"  ./../illegal\n"*6)
            with patch.object(h,"OFFLINE",root):
                with self.assertRaisesRegex(ValueError,"invalid"):
                    h.bound_offline_evidence()

    def test_execute_without_both_acks_fails_before_preview(self):
        cases=[
            ["prog","--prepare","--expected-head","a"*40],
            ["prog","--prepare","--expected-head","a"*40,"--ack-claim"],
            ["prog","--preview","--expected-head","a"*40,"--ack-claim"],
        ]
        for case in cases:
            with self.subTest(case=case),(
                 patch.object(sys,"argv",case)),(
                 patch.object(h,"preview",side_effect=AssertionError("preview"))),(
                 redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit) as ex:
                    h.main()
                self.assertEqual(ex.exception.code,2)

    def test_scheduler_unknown_cannot_use_initial_healthy_quota(self):
        with patch.object(h,"validate_admission",return_value={}),(
             patch.object(h.QuotaSnapshot,"model_validate",
                          return_value=Mock(account="x",provider="x"))),(
             patch.object(h,"unknown_quota_snapshot",return_value=Mock())),(
             patch.object(h,"digest",return_value="unknown")):
                with self.assertRaisesRegex(ValueError,"unknown"):
                    h.admission({"snapshot":{}},{"quota_snapshot_digest":"unknown"})

    def test_provider_error_before_prepare_never_dispatches(self):
        with TemporaryDirectory() as td:
            out=Path(td)/"attempt2"
            with patch.object(h,"OUT",out),(
                 patch.object(h.old,"run_read",
                              side_effect=RuntimeError("sensitive-provider-message")),(
                 patch.object(h.subprocess,"run",
                              side_effect=AssertionError("NO DISPATCH"))):
                result=h.prepare_once({"target":"frozen","research_head":"a"*40})
            self.assertEqual(result["decision"],
                "D2_CTL_ATTEMPT2_PRECLAIM_BLOCKED__NO_RETRY")
            self.assertFalse(result["prepare_dispatched"])
            self.assertEqual(result["retries"],0)
            self.assertNotIn("sensitive",json.dumps(result))

    def test_timeout_dispatches_at_most_once(self):
        with TemporaryDirectory() as td:
            out=Path(td)/"attempt2"
            calls=[json.dumps({"snapshot":{}}),json.dumps({"candidates":[]}),
                   "{}","{}"]
            invocation_count=[0]
            def timeout(argv,**kwargs):
                invocation_count[0]+=1
                raise subprocess.TimeoutExpired(argv,180)
            ready={"decision":
                "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"}
            initial={"target":"frozen","research_head":"a"*40}
            with patch.object(h,"OUT",out),(
                 patch.object(h.old,"run_read",side_effect=calls)),(
                 patch.object(h,"admission",return_value={})),(
                 patch.object(h,"validate_strategy")),(
                 patch.object(h.historical,"preview_attempt2",return_value=ready)),(
                 patch.object(h.old,"git",side_effect=lambda root,*args:
                              "frozen" if "branch" in args else "a"*40)),(
                 patch.object(h.subprocess,"run",side_effect=timeout)):
                result=h.prepare_once(initial)
            self.assertEqual(invocation_count[0],1)
            self.assertEqual(result["decision"],
                "D2_CTL_ATTEMPT2_DISPATCHED_NEEDS_RECONCILIATION__NO_RETRY")
            self.assertTrue(result["prepare_dispatched"])
            self.assertTrue(result["timed_out"])
            self.assertFalse(result["worker_started"])

    def test_evidence_identity_never_reused(self):
        with TemporaryDirectory() as td:
            out=Path(td)/"attempt2"
            out.mkdir()
            with patch.object(h,"OUT",out),(
                 patch.object(h.old,"run_read",
                              side_effect=AssertionError("no quota"))):
                with self.assertRaises(FileExistsError):
                    h.prepare_once({"target":"frozen"})


if __name__ == "__main__":
    unittest.main()
