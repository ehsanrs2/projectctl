"""Offline synthetic tests of read-only, sanitized D2 Attempt-2 diagnostics."""
from __future__ import annotations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from experiments.dogfooding.d2 import d2_ctl_attempt2_admission_forensics as h


def records():
    summary = {
        "decision": h.EXPECTED, "failure_stage": "admission",
        "attempt": 2, "retries": 0, "worker_started": False,
        "prepare_dispatched": False, "finished_utc": "2026-10-21T12:00:00Z",
    }
    quota = {
        "mode": "normal", "stale": False,
        "effective": {"five_hour": .72, "weekly": .87},
        "snapshot": {
            "account": "DO-NOT-DISCLOSE",
            "provider": "codex_app_server", "selected_limit_id": "codex",
            "ordinary_usage_allowed": True,
            "observed_at": "2026-10-21T11:59:40Z",
            "five_hour": {"source": "official", "confidence": "high"},
            "weekly": {"source": "official", "confidence": "high"},
        },
    }
    scheduler = {
        "quota_mode": "conservation", "selected_task_id": None,
        "candidates": [{
            "task_id": h.TASK, "model": None,
            "eligibility": {"eligible": False, "reasons": ["quota_unknown"]},
        }],
    }
    return summary, quota, scheduler


class ReadOnlyForensicsTests(unittest.TestCase):
    def test_synthetic_unknown_digest_is_reported(self):
        s,q,n = records()
        r = h.analyze(s,q,n,"canonical_unknown")
        self.assertTrue(r["checks"]["first_quota_official_normal"])
        self.assertFalse(r["checks"]["scheduler_normal_selected"])
        self.assertEqual(r["candidate_reason_codes"],["quota_unknown"])
        self.assertNotIn("DO-NOT-DISCLOSE",json.dumps(r))

    def test_threshold_failure_is_separate(self):
        s,q,n = records()
        q["effective"]["weekly"] = 0.01
        self.assertIn("weekly_medium_floor",
                      h.analyze(s,q,n,"different")["failed_checks"])

    def test_boolean_effective_ratio_is_rejected(self):
        s,q,n = records()
        q["effective"]["five_hour"] = True
        self.assertFalse(h.analyze(s,q,n,"different")["checks"][
            "five_hour_medium_floor"])

    def test_worker_started_refused(self):
        s,q,n = records()
        s["worker_started"] = True
        with self.assertRaisesRegex(ValueError,"Unexpected Attempt-2"):
            h.analyze(s,q,n,"canonical_unknown")

    def test_prepare_intent_refused(self):
        s,q,n = records()
        s["prepare_dispatch_intent_utc"] = "2026-10-21T12:00:00Z"
        with self.assertRaises(ValueError):
            h.analyze(s,q,n,"canonical_unknown")

    def test_raw_reason_is_sanitized(self):
        s,q,n = records()
        n["candidates"][0]["eligibility"]["reasons"] = ["secret-provider-message"]
        r = h.analyze(s,q,n,"unclassified")
        self.assertEqual(r["candidate_reason_codes"],["other"])
        self.assertNotIn("secret-provider-message",json.dumps(r))

    def test_symlink_is_refused(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder/"source"
            target.write_text("{}")
            (folder/"prepare-summary.json").symlink_to(target)
            with self.assertRaisesRegex(ValueError,"symlinked"):
                h.read_json(folder,"prepare-summary.json")

    def test_missing_file_is_refused(self):
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,"Missing"):
                h.read_json(Path(temp),"missing.json")

    def test_post_dispatch_evidence_refused(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp)
            s,q,n=records()
            for name,data in zip(h.NAMES,(s,q,n)):
                (folder/name).write_text(json.dumps(data))
            (folder/"prepare.json").write_text("{}")
            with patch.object(h,"relation",side_effect=AssertionError("no analysis")):
                with self.assertRaisesRegex(ValueError,"dispatch evidence"):
                    h.inspect(folder)

    def test_inspection_makes_no_changes(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp)
            s,q,n=records()
            for name,data in zip(h.NAMES,(s,q,n)):
                (folder/name).write_text(json.dumps(data))
            before={p.name:p.read_bytes() for p in folder.iterdir()}
            with patch.object(h,"relation",return_value="canonical_unknown"):
                report=h.inspect(folder)
            self.assertEqual(before,{p.name:p.read_bytes()
                                     for p in folder.iterdir()})
            self.assertTrue(report["no_provider_calls"])


if __name__ == "__main__":
    unittest.main()
