"""Tests for D1 fixture policy setup's explicit consent and safe path guard."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d1_prepare_policy as mod


class D1PolicyPreparationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="pctl-d1-policy-tests-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.target = self.root / "example.txt"
        self.target.write_text("original", encoding="utf-8")

    def invoke(self, flags):
        result = io.StringIO()
        with (patch.object(sys, "argv", ["d1_prepare_policy.py", "--repo", str(self.root), *flags]),
              patch.object(mod, "prepare", return_value=(
                  self.root, {self.target: "new-value"}, {"example.txt": "test-sha"})),
              contextlib.redirect_stdout(result)):
            return mod.main(), json.loads(result.getvalue())

    def test_preview_only_does_not_write(self):
        code, data = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "PREVIEW_ONLY")
        self.assertEqual(self.target.read_text(), "original")

    def test_both_flags_are_required_to_write(self):
        for flags in (["--apply"], ["--ack-disposable"]):
            code, data = self.invoke(flags)
            self.assertEqual(code, 0)
            self.assertEqual(data["status"], "PREVIEW_ONLY")
            self.assertEqual(self.target.read_text(), "original")

    def test_explicit_apply_modifies_only_declared_target(self):
        code, data = self.invoke(["--apply", "--ack-disposable"])
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "POLICY_FILES_WRITTEN")
        self.assertEqual(self.target.read_text(), "new-value")

    def test_unexpected_repo_location_is_rejected(self):
        before = self.target.read_bytes()
        with self.assertRaises(ValueError):
            mod.prepare(self.root)
        self.assertEqual(self.target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
