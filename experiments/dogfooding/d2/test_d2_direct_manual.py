"""Offline-only D2 Direct CLI harness tests. NEVER launch a Codex model turn."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from experiments.dogfooding.d2 import d2_direct_manual as h


FIXED_NOW = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)


def valid_quota():
    return {
        "stale": False, "mode": "normal",
        "effective": {"five_hour": .9, "weekly": .75},
        "snapshot": {
            "provider": "codex_app_server",
            "selected_limit_id": "codex",
            "ordinary_usage_allowed": True,
            "observed_at": "2026-10-20T13:59:30Z",
            "five_hour": {"source": "official", "confidence": "high"},
            "weekly": {"source": "official", "confidence": "high"},
        },
    }


def valid_next():
    return {
        "selected_task_id": "d2ctl-g4q",
        "quota_mode": "normal",
        "quota_snapshot_digest": "canonical-json-sha256-v1:some-digest",
        "candidates": [
            {"task_id": "d2ctl-g4q",
             "eligibility": {"eligible": True, "reasons": []},
             "model": {"profile": "balanced", "reasoning": "medium"}}
        ],
    }


class D2DirectHarnessTests(TestCase):
    def admit(self, quota=None, decision=None, now=FIXED_NOW):
        return h.validate_admission(
            quota if quota is not None else valid_quota(),
            decision if decision is not None else valid_next(),
            now=now)

    def test_current_high_confidence_official_eligible(self):
        x = self.admit()
        self.assertEqual(x["selected_task_id"], "d2ctl-g4q")
        self.assertEqual(x["five_hour_effective"], .9)

    def test_stale_snapshot_refused(self):
        quota = valid_quota()
        quota["stale"] = True
        with self.assertRaisesRegex(ValueError, "not authorized"):
            self.admit(quota)

    def test_manual_provider_refused(self):
        quota = valid_quota()
        quota["snapshot"]["provider"] = "manual"
        with self.assertRaises(ValueError):
            self.admit(quota)

    def test_wrong_quota_bucket_refused(self):
        quota = valid_quota()
        quota["snapshot"]["selected_limit_id"] = "other"
        with self.assertRaises(ValueError):
            self.admit(quota)

    def test_old_sample_refused(self):
        quota = valid_quota()
        quota["snapshot"]["observed_at"] = "2026-10-20T13:55:00Z"
        with self.assertRaisesRegex(ValueError, "too old"):
            self.admit(quota)

    def test_insufficient_medium_five_hour_refused(self):
        quota = valid_quota()
        quota["effective"]["five_hour"] = .17
        with self.assertRaisesRegex(ValueError, "five-hour"):
            self.admit(quota)

    def test_insufficient_medium_weekly_refused(self):
        quota = valid_quota()
        quota["effective"]["weekly"] = .07
        with self.assertRaisesRegex(ValueError, "weekly"):
            self.admit(quota)

    def test_official_confidence_required(self):
        quota = valid_quota()
        quota["snapshot"]["five_hour"]["source"] = "cached"
        with self.assertRaisesRegex(ValueError, "high-confidence"):
            self.admit(quota)

    def test_scheduler_must_select_sole_task(self):
        decision = valid_next()
        decision["selected_task_id"] = None
        with self.assertRaisesRegex(ValueError, "did not select"):
            self.admit(decision=decision)

    def test_scheduler_ineligible_refused(self):
        decision = valid_next()
        decision["candidates"][0]["eligibility"]["eligible"] = False
        with self.assertRaisesRegex(ValueError, "admission failed"):
            self.admit(decision=decision)

    def test_scheduler_profile_mismatch_refused(self):
        decision = valid_next()
        decision["candidates"][0]["model"]["reasoning"] = "high"
        with self.assertRaisesRegex(ValueError, "profile"):
            self.admit(decision=decision)

    def test_single_completed_turn_usage_is_not_double_counted(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"events.jsonl"
            events = [
                {"type": "thread.started", "thread_id": "fresh"},
                {"type": "turn.started"},
                {"type": "turn.completed", "usage": {
                    "input_tokens": 125,
                    "cached_input_tokens": 75,
                    "output_tokens": 21,
                    "reasoning_output_tokens": 7}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in events)+"\n")
            data = h.parse_events(path)
            self.assertTrue(data["single_completed_turn"])
            self.assertEqual(data["usage"]["input_tokens"], 125)
            self.assertEqual(data["usage"]["cached_input_tokens"], 75)
            self.assertIn("subsets", data["usage_accounting_note"])

    def test_malformed_json_event_fails_single_turn(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"events.jsonl"
            path.write_text('{"type":"turn.started"}\nNOT JSON\n')
            result = h.parse_events(path)
            self.assertFalse(result["single_completed_turn"])
            self.assertEqual(result["malformed_lines"], 1)
            self.assertEqual(result["usage"], "unknown")

    def test_missing_token_usage_remains_unknown(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"events.jsonl"
            path.write_text(
                '{"type":"thread.started","thread_id":"x"}\n'
                '{"type":"turn.started"}\n{"type":"turn.completed"}\n')
            result = h.parse_events(path)
            self.assertTrue(result["single_completed_turn"])
            self.assertEqual(result["usage"], "unknown")

    def test_changed_paths_includes_ignored_artifacts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            def g(*args):
                return subprocess.run(["git","-C",str(root),*args],
                                      capture_output=True,check=True)
            g("init","-q")
            g("config","user.name","D2 Offline Test")
            g("config","user.email","offline@invalid.example")
            (root/".gitignore").write_text("*.db\n")
            (root/"source.py").write_text("x=1\n")
            g("add",".gitignore","source.py")
            g("-c","commit.gpgsign=false","commit","-qm","offline")
            (root/"source.py").write_text("x=2\n")
            (root/"unexpected.db").write_text("hidden\n")
            self.assertEqual(h.changed_paths(root), {"source.py","unexpected.db"})

    def test_preview_never_calls_paid_execute(self):
        args = ["d2_direct_manual", "--preview"]
        preflight_output = {
            "decision": "D2_NO_INFERENCE_PREFLIGHT_PASS",
            "predeclared_order": ["direct_cli","projectctl"],
        }
        output=io.StringIO()
        with (patch.object(sys,"argv",args),
              patch.object(h,"preflight",return_value=("prompt",preflight_output)),
              patch.object(h,"execute",side_effect=AssertionError("paid call forbidden")),
              redirect_stdout(output)):
            self.assertEqual(h.main(),0)
        self.assertIn("NO_PAID_CALL",output.getvalue())

    def test_paid_flag_requires_explicit_ack(self):
        args = ["d2_direct_manual", "--execute"]
        stderr=io.StringIO()
        with (patch.object(sys,"argv",args),
              patch.object(h,"preflight",side_effect=AssertionError("must not preflight")),
              patch.object(h,"execute",side_effect=AssertionError("must not call")),
              redirect_stderr(stderr)):
            with self.assertRaises(SystemExit) as ctx:
                h.main()
        self.assertEqual(ctx.exception.code,2)
        self.assertIn("requires --execute --ack-paid",stderr.getvalue())


if __name__ == "__main__":
    import unittest
    unittest.main()
