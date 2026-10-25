"""Synthetic-only safety qualification for D2 Attempt-3 one-shot Prepare candidate."""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stderr

from experiments.dogfooding.d2 import d2_ctl_attempt3_prepare_once as h


def eligible_initial():
    return {"research_head": "a"*40, "target": "main",
            "decision": "D2_ATTEMPT3_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"}


class Attempt3PrepareTests(unittest.TestCase):
    def test_requires_exact_reviewed_sha(self):
        with self.assertRaisesRegex(ValueError, "Exact reviewed research SHA"):
            h.preview("HEAD")

    def test_reused_attempt3_directory_refused(self):
        with TemporaryDirectory() as td:
            directory = Path(td)/"used"
            directory.mkdir()
            with patch.object(h, "OUT", directory):
                with self.assertRaisesRegex(ValueError, "NO RETRY"):
                    h.preview("a"*40)

    def test_no_prepare_without_both_approvals(self):
        cases = [
            ["tool", "--prepare", "--expected-head", "a"*40],
            ["tool", "--prepare", "--expected-head", "a"*40, "--ack-claim"],
            ["tool", "--prepare", "--expected-head", "a"*40,
             "--approval-phrase", h.ACK],
            ["tool", "--preview", "--expected-head", "a"*40, "--ack-claim"],
        ]
        for case in cases:
            with (
                self.subTest(args=case),
                patch.object(sys, "argv", case),
                patch.object(h, "preview", side_effect=AssertionError("not previewed")),
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as caught:
                    h.main()
                self.assertEqual(caught.exception.code, 2)

    def test_qualified_manifest_missing_fails_closed(self):
        with TemporaryDirectory() as td:
            with patch.object(h, "OFFLINE", Path(td)/"none"):
                with self.assertRaisesRegex(ValueError, "missing"):
                    h.offline_bound()

    def test_bad_offline_qualification_rejected(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            (root/"result.txt").write_text(
                "decision=D2_ATTEMPT3_OFFLINE_BLOCKED\n"
                "research_commit="+h.QUALIFIED_SHA+"\nexit_code=2\n")
            with patch.object(h, "OFFLINE", root):
                with self.assertRaisesRegex(ValueError, "drift"):
                    h.offline_bound()

    def test_live_runner_checks_real_quota_schema(self):
        quota={"snapshot":{"schema_version":2}}
        with self.assertRaises(h.offline.AdmissionBlocked) as blocked:
            h.first_admission(quota, datetime.now(timezone.utc))
        self.assertEqual(blocked.exception.code, "quota_schema_invalid")

    def test_first_quota_block_prevents_scheduler(self):
        with TemporaryDirectory() as td:
            directory = Path(td)/"attempt3"
            count=[]
            def request(argv, **kwargs):
                count.append(argv[1])
                if argv[1] == "quota":
                    return json.dumps({"mode":"conservation"})
                raise AssertionError("Scheduler and Prepare must not run")
            with (
                patch.object(h, "OUT", directory),
                patch.object(h.old, "run_read", side_effect=request),
                patch.object(h.subprocess, "run", side_effect=AssertionError("no Prepare")),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(count, ["quota"])
            self.assertEqual(result["decision"], h.BLOCKED)
            self.assertEqual(result["failure_stage"], "first_quota")
            self.assertFalse(result["prepare_dispatched"])
            self.assertFalse(result["worker_started"])
            self.assertEqual(result["retries"], 0)

    def test_second_unknown_prevents_prepare(self):
        with TemporaryDirectory() as td:
            directory = Path(td)/"attempt3"
            seen=[]
            def request(argv, **kwargs):
                seen.append(argv[1])
                return "{}"
            with (
                patch.object(h, "OUT", directory),
                patch.object(h.old, "run_read", side_effect=request),
                patch.object(h, "first_admission", return_value={"snapshot":Mock()}),
                patch.object(h, "second_admission",
                             side_effect=h.offline.AdmissionBlocked("scheduler_unknown_quota")),
                patch.object(h.subprocess, "run", side_effect=AssertionError("no Prepare")),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(seen, ["quota", "next"])
            self.assertFalse(result["prepare_dispatched"])
            self.assertEqual(result["reason_code"], "scheduler_unknown_quota")

    def test_second_insufficient_prevents_prepare(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"attempt3"
            with (
                patch.object(h, "OUT", directory),
                patch.object(h.old, "run_read", return_value="{}"),
                patch.object(h, "first_admission", return_value={"snapshot":Mock()}),
                patch.object(h, "second_admission",
                             side_effect=h.offline.AdmissionBlocked("scheduler_rejected")),
                patch.object(h.subprocess, "run", side_effect=AssertionError("no Prepare")),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(result["decision"], h.BLOCKED)
            self.assertEqual(result["failure_stage"], "scheduler")

    def test_rejected_strategy_cannot_dispatch(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"attempt3"
            with (
                patch.object(h, "OUT", directory),
                patch.object(h.old, "run_read", return_value="{}"),
                patch.object(h, "first_admission", return_value={"snapshot":Mock()}),
                patch.object(h, "second_admission"),
                patch.object(h, "validate_strategy", side_effect=ValueError("reject")),
                patch.object(h.subprocess, "run", side_effect=AssertionError("no Prepare")),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(result["decision"], h.BLOCKED)
            self.assertEqual(result["failure_stage"], "capabilities")

    def test_timeout_dispatches_once_with_durable_intent(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"attempt3"
            called=[]
            def timeout(argv, **kwargs):
                called.append(argv)
                self.assertTrue((directory/"prepare-summary.json").is_file())
                before=json.loads((directory/"prepare-summary.json").read_text())
                self.assertTrue(before["prepare_dispatched"])
                raise subprocess.TimeoutExpired(argv, 180)
            with (
                patch.object(h, "OUT", directory),
                patch.object(h.old, "run_read", return_value="{}"),
                patch.object(h, "first_admission", return_value={"snapshot":Mock()}),
                patch.object(h, "second_admission"),
                patch.object(h, "validate_strategy"),
                patch.object(h, "preflight_again"),
                patch.object(h.subprocess, "run", side_effect=timeout),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(len(called),1)
            self.assertEqual(called[0][1:3],["run","prepare"])
            self.assertTrue(result["prepare_dispatched"])
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["decision"], h.AMBIGUOUS)
            self.assertEqual(result["retries"],0)

    def test_one_prepare_mock_success_never_starts_worker(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"attempt3"
            commands=[]
            def spy(argv, **kwargs):
                commands.append(argv)
                return subprocess.CompletedProcess(argv, 0, '{"plan":{},"run":{},"worktree":{}}', '')
            with (
                patch.object(h,"OUT",directory),
                patch.object(h.old,"run_read",return_value="{}"),
                patch.object(h,"first_admission",return_value={"snapshot":Mock()}),
                patch.object(h,"second_admission"),
                patch.object(h,"validate_strategy"),
                patch.object(h,"preflight_again"),
                patch.object(h,"postflight",return_value={"run_id":"run-synthetic"}),
                patch.object(h.subprocess,"run",side_effect=spy),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(result["decision"],h.PASS)
            self.assertFalse(result["worker_started"])
            self.assertEqual(result["run_id"],"run-synthetic")
            self.assertEqual(len(commands),1)
            self.assertEqual(commands[0][1:3],["run","prepare"])

    def test_no_second_prepare_after_existing_identity(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"used"
            directory.mkdir()
            with (
                patch.object(h,"OUT",directory),
                patch.object(h.old,"run_read",
                             side_effect=AssertionError("no provider")),
            ):
                with self.assertRaises(FileExistsError):
                    h.prepare_once(eligible_initial())

    def test_logging_sanitizes_provider_message(self):
        with TemporaryDirectory() as td:
            directory=Path(td)/"attempt3"
            with (
                patch.object(h,"OUT",directory),
                patch.object(h.old,"run_read",
                             side_effect=RuntimeError("secret account-key")),
            ):
                result=h.prepare_once(eligible_initial())
            self.assertEqual(result["decision"],h.BLOCKED)
            self.assertNotIn("secret",json.dumps(result))
            self.assertNotIn("secret",(directory/"prepare-summary.json").read_text())

    def test_missing_manifest_result_not_interpreted_as_qualified(self):
        with TemporaryDirectory() as td:
            directory=Path(td)
            (directory/"result.txt").write_text(
                "decision=D2_ATTEMPT3_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED\n"
                "last_step=complete\nexit_code=0\nresearch_commit="+h.QUALIFIED_SHA+
                "\nattempt3_prepare_dispatched=false\npaid_worker_started=false\n")
            with patch.object(h,"OFFLINE",directory):
                with self.assertRaises(ValueError):
                    h.offline_bound()


if __name__=="__main__":
    unittest.main()
