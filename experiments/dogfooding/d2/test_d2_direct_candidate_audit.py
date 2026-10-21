"""Offline, no-user-fixture tests for completed D2 Direct evidence audit."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.dogfooding.d2 import d2_direct_candidate_audit as mod
from experiments.dogfooding.d2.d2_direct_manual import EXPECTED, PROMPT_SHA

def good_events():
    return {
        "event_counts": {"thread.started":1, "turn.started":1,
                         "turn.completed":1},
        "malformed_lines":0,
        "thread_count":1,
        "usage":{"input_tokens":97,"cached_input_tokens":32,
                 "output_tokens":8,"reasoning_output_tokens":2},
        "single_completed_turn":True,
        "usage_accounting_note": "cached_input_tokens and reasoning_output_tokens are subsets, not additional totals",
    }

def good_summary():
    return {
        "status":mod.SUCCESS,
        "codex_exit_code":0, "timed_out":False,
        "attempt":1, "retries":0,
        "model_requested":"gpt-6-luna",
        "reasoning_requested":"medium",
        "runtime_requested":"codex-cli 0.163.0",
        "approval":"never", "sandbox":"workspace-write",
        "network":"disabled", "plugins_and_apps":"disabled",
        "prompt_sha256":PROMPT_SHA,
        "codex_wall_monotonic_seconds":32.8,
        "start_utc":"2026-10-20T14:00:00+00:00",
        "end_utc":"2026-10-20T14:00:33+00:00",
        "verification":{"exit_code":0, "test_count":26,
                        "wall_monotonic_seconds":0.16},
        "scope":{"changed_paths":sorted(EXPECTED),
                 "protected_hashes":"match",
                 "direct_git_head":mod.BASE,
                 "ctl_git_head":mod.POLICY_HEAD},
        "post_test_scope":{"changed_paths":sorted(EXPECTED),
                           "protected_hashes":"match",
                           "direct_git_head":mod.BASE,
                           "ctl_git_head":mod.POLICY_HEAD},
        "events":good_events(),
    }


class DirectReadOnlyAuditTests(unittest.TestCase):
    def test_valid_single_turn_summary(self):
        mod.validate_summary(good_summary(), good_events())

    def test_failed_codex_exit_refused(self):
        data=good_summary()
        data["codex_exit_code"]=1
        with self.assertRaisesRegex(ValueError,"status"):
            mod.validate_summary(data,good_events())

    def test_duplicate_retries_refused(self):
        data=good_summary()
        data["retries"]=1
        with self.assertRaisesRegex(ValueError,"status"):
            mod.validate_summary(data,good_events())

    def test_tool_network_drift_refused(self):
        data=good_summary()
        data["network"]="enabled"
        with self.assertRaisesRegex(ValueError,"envelope drift: network"):
            mod.validate_summary(data,good_events())

    def test_wrong_prompt_refused(self):
        data=good_summary()
        data["prompt_sha256"]="not-the-frozen-sha"
        with self.assertRaisesRegex(ValueError,"envelope drift: prompt_sha256"):
            mod.validate_summary(data,good_events())

    def test_test_count_must_be_exact(self):
        data=good_summary()
        data["verification"]["test_count"]=25
        with self.assertRaisesRegex(ValueError,"26 passing"):
            mod.validate_summary(data,good_events())

    def test_post_test_scope_drift_refused(self):
        data=good_summary()
        data["post_test_scope"]["changed_paths"]=sorted(EXPECTED)[:2]
        with self.assertRaisesRegex(ValueError,"post_test_scope"):
            mod.validate_summary(data,good_events())

    def test_jsonl_counter_mismatch_refused(self):
        data=good_summary()
        changed=good_events()
        changed["event_counts"]["turn.started"]=2
        with self.assertRaisesRegex(ValueError,"raw JSONL"):
            mod.validate_summary(data,changed)

    def test_syntax_and_import_inventory(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"s.py"
            p.write_text("import json\nfrom pathlib import Path\nx = 1\n",encoding="utf-8")
            result=mod.source_inventory(Path(td),{"s.py"})
            self.assertEqual(result["s.py"]["sha256"],
                             hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(result["s.py"]["imports_to_review"],["json","pathlib"])

    def test_syntax_invalid_source_refused(self):
        with TemporaryDirectory() as td:
            (Path(td)/"s.py").write_text("def no(:\n")
            with self.assertRaises(SyntaxError):
                mod.source_inventory(Path(td),{"s.py"})

    def test_git_porcelain_preserves_leading_status_space(self):
        with patch.object(mod,"command",return_value=" M d2events/parse.py\n"):
            self.assertEqual(mod.git(Path("/unrelated"),"status","--porcelain"),
                             " M d2events/parse.py")

    def test_readonly_flag_required(self):
        from contextlib import redirect_stderr
        import io,sys
        args=["d2_direct_candidate_audit"]
        with (patch.object(sys,"argv",args),
              patch.object(mod,"audit",side_effect=AssertionError("must never run")),
              redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as ex:
                mod.main()
        self.assertEqual(ex.exception.code,2)

    def test_missing_report_fails_closed(self):
        with TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,"Missing"):
                mod.json_file(Path(td)/"no-evidence.json")


if __name__ == "__main__":
    unittest.main()
