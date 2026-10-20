"""Offline qualification for deterministic D2 fixtures. Never invokes a model."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiments.dogfooding.d2 import build_fixture as fixture


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, timeout=30
    )
    return result.stdout.strip()


class D2FixtureBuilderTests(unittest.TestCase):
    def test_expected_three_source_write_paths_and_protected_tests(self):
        sources = {p for p in fixture.FILES if p.startswith("d2events/") and p.endswith(".py")}
        self.assertEqual(sources, {
            "d2events/__init__.py", "d2events/parse.py",
            "d2events/report.py", "d2events/cli.py"
        })
        self.assertIn("Only d2events/parse.py", fixture.POLICY)
        self.assertIn("duplicate JSON object keys", fixture.SPEC)
        self.assertIn("first_seen", fixture.SPEC)
        self.assertEqual(len(fixture.FILES), 11)

    def test_all_frozen_test_sources_parse_and_count(self):
        test_sources = [v for k, v in fixture.FILES.items() if k.startswith("tests/test_")]
        cases = 0
        for source in test_sources:
            tree = ast.parse(source)
            cases += sum(
                isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
                for node in ast.walk(tree)
            )
        self.assertEqual(cases, 26)
        self.assertEqual(len(test_sources), 3)

    def test_stub_sources_are_syntactically_valid_and_unimplemented(self):
        for name in ("d2events/parse.py", "d2events/report.py", "d2events/cli.py"):
            code = fixture.FILES[name]
            ast.parse(code)
            self.assertIn("raise NotImplementedError", code)

    def test_two_new_fixtures_have_identical_sha_and_clean_state(self):
        with tempfile.TemporaryDirectory(prefix="d2-fixture-offline-") as tmp:
            root = Path(tmp)
            a = fixture.build(root / "ctl", output_root=root)
            z = fixture.build(root / "direct", output_root=root)
            self.assertEqual(a, z)
            self.assertEqual(_git(root / "ctl", "rev-parse", "HEAD"), a["baseline_commit"])
            self.assertEqual(_git(root / "direct", "rev-parse", "HEAD"), a["baseline_commit"])
            self.assertTrue(len(a["spec_sha256"]) == 64)
            self.assertEqual(_git(root / "ctl", "status", "--porcelain"), "")
            self.assertEqual(_git(root / "direct", "status", "--porcelain"), "")
            self.assertEqual(_git(root / "ctl", "remote"), "")
            self.assertEqual(_git(root / "direct", "remote"), "")
            self.assertEqual((root / "ctl" / "SPEC.md").read_bytes(),
                             (root / "direct" / "SPEC.md").read_bytes())
            with self.assertRaises(FileExistsError):
                fixture.build(root / "ctl", output_root=root)

    def test_refuses_output_root_inside_git_repo(self):
        with tempfile.TemporaryDirectory(prefix="d2-fixture-guard-") as tmp:
            root = Path(tmp)
            subprocess.run(["git","-C",str(root),"init","--quiet"],
                           capture_output=True,check=True,timeout=10)
            with self.assertRaises(ValueError):
                fixture.build(root / "illegal", output_root=root)
            self.assertFalse((root / "illegal").exists())

    def test_baseline_acceptance_does_not_pass_on_stubs(self):
        with tempfile.TemporaryDirectory(prefix="d2-fixture-negative-") as tmp:
            root = Path(tmp)
            fixture.build(root/"baseline",output_root=root)
            res = subprocess.run(
                [sys.executable,"-B","-m","unittest","discover","-s","tests",
                 "-p","test_*.py","-v"],
                cwd=root/"baseline",capture_output=True,text=True,
                check=False,timeout=30,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("NotImplementedError", res.stderr)
            self.assertIn("Ran 26 tests", res.stderr)


if __name__ == "__main__":
    unittest.main()
