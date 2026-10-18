from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_fixture  # noqa: E402
import preflight  # noqa: E402


class D0ToolTests(unittest.TestCase):
    def setUp(self):
        self.output = HERE / ".selftest-output"
        if self.output.exists():
            shutil.rmtree(self.output)
        self.output.mkdir()

    def tearDown(self):
        if self.output.exists():
            shutil.rmtree(self.output)

    def test_preflight_schema_and_offline_safety_flags(self):
        report = preflight.inspect()
        self.assertEqual(report["schema"], "projectctl.dogfooding_d0_preflight.v1")
        self.assertEqual(report["mode"], "offline_read_only_zero_inference")
        self.assertFalse(report["isolation"]["secrets_read"])
        self.assertFalse(report["isolation"]["network_used"])
        self.assertFalse(report["isolation"]["projectctl_state_mutated"])
        self.assertIn("SDK_MODEL_RUNTIME_UNVERIFIED", {item["code"] for item in report["blockers"]})
        json.dumps(report)

    def test_fixture_builder_reproduces_same_clean_local_baseline(self):
        build_fixture.OUTPUT_ROOT = self.output
        first = build_fixture.build(self.output / "arm-a")
        second = build_fixture.build(self.output / "arm-b")
        self.assertEqual(first, second)
        self.assertEqual((self.output / "arm-a" / "POLICY.md").read_bytes(),
                         (self.output / "arm-b" / "POLICY.md").read_bytes())
        for name in ("arm-a", "arm-b"):
            root = self.output / name
            status = __import__("subprocess").run(["git", "-C", str(root), "status", "--porcelain"],
                                                   capture_output=True, text=True, check=True).stdout
            remotes = __import__("subprocess").run(["git", "-C", str(root), "remote"],
                                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(status, "")
            self.assertEqual(remotes, "")

    def test_builder_refuses_path_outside_isolated_root(self):
        with self.assertRaises(ValueError):
            build_fixture.build(HERE.parent / "forbidden-output")

    def test_preflight_reports_cleanliness_without_emitting_repo_path(self):
        build_fixture.OUTPUT_ROOT = self.output
        repo = self.output / "clean-repo"
        build_fixture.build(repo)
        clean_report = preflight.inspect(repo)
        self.assertTrue(clean_report["repository"]["is_git"])
        self.assertTrue(clean_report["repository"]["clean"])
        self.assertFalse(clean_report["repository"]["has_remote"])
        self.assertNotIn(str(repo), json.dumps(clean_report))
        (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
        dirty_report = preflight.inspect(repo)
        self.assertFalse(dirty_report["repository"]["clean"])
        self.assertIn("REPO_DIRTY", {item["code"] for item in dirty_report["blockers"]})


if __name__ == "__main__":
    unittest.main()
