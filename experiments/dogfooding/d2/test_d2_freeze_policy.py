"""Offline contract tests for D2 local scope/verification freeze. Never runs Codex."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.execution_scope import ExecutionScopeCatalog
from projectctl.schemas.verification import VerificationCatalog

from experiments.dogfooding.d2 import d2_freeze_policy as mod


class D2PolicyFreezeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="projectctl-d2-policy-offline-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_allowed_source_is_exact_three_files(self):
        self.assertEqual(mod.ALLOWED_SOURCE, {
            "d2events/parse.py", "d2events/report.py", "d2events/cli.py",
        })
        self.assertEqual(mod.TASK, "d2ctl-g4q")
        self.assertEqual(len(mod.TRACKED_COMMIT), 4)

    def test_original_adoption_five_untracked_paths_are_pinned(self):
        self.assertEqual(mod.EXPECTED_UNTRACKED, {
            "?? .projectctl/adoption.yaml", "?? .projectctl/config.yaml",
            "?? .projectctl/state.sqlite", "?? .projectctl/telemetry.sqlite",
            "?? docs/PROJECT_STATE.yaml",
        })

    def test_do_not_trim_git_status_prefix(self):
        with patch.object(mod, "run", return_value=SimpleNamespace(
                stdout=" M .gitignore\n?? projectctl.scope.yaml\n")):
            self.assertEqual(mod.git(self.root, "status", "--porcelain"),
                             " M .gitignore\n?? projectctl.scope.yaml")

    def test_config_scope_and_verification_are_schema_valid(self):
        cfg=ProjectConfig(project=ProjectIdentity(id="d2",name="d2"))
        files=mod.build_outputs(self.root,cfg.model_dump(mode="json"),
                                "__pycache__/\n*.py[cod]\n.dolt/\n")
        self.assertEqual({x.relative_to(self.root).as_posix() for x in files},
                {".gitignore",".projectctl/config.yaml",
                 "projectctl.scope.yaml","projectctl.verification.yaml"})
        parsed_config=ProjectConfig.model_validate(
            yaml.safe_load(files[self.root/".projectctl/config.yaml"]))
        self.assertEqual(parsed_config.scope_governance.mode,"required")
        self.assertEqual(parsed_config.orchestration.max_active_runs,1)
        self.assertTrue(all(p.model=="gpt-6-luna" and p.reasoning.value=="medium"
                            for p in parsed_config.model_profiles.values()))
        scope=ExecutionScopeCatalog.model_validate(
            yaml.safe_load(files[self.root/"projectctl.scope.yaml"]))
        self.assertEqual(set(scope.tasks),{"d2ctl-g4q"})
        self.assertEqual({i.path for i in scope.tasks[mod.TASK].writes},mod.ALLOWED_SOURCE)
        self.assertTrue(all(i.kind=="exact" for i in scope.tasks[mod.TASK].writes))
        v=VerificationCatalog.model_validate(
            yaml.safe_load(files[self.root/"projectctl.verification.yaml"]))
        p=v.profiles[v.default_profile]
        self.assertEqual(p.commands[0].argv,mod.CHECK)
        self.assertTrue(p.commands[0].required)
        self.assertEqual(p.commands[0].timeout_seconds,120)
        self.assertEqual(p.diff_policy.max_changed_paths,3)
        for path in ("SPEC.md","POLICY.md","tests/**","d2events/__init__.py",
                     ".gitignore","projectctl.scope.yaml","projectctl.verification.yaml",
                     ".projectctl/**"):
            self.assertIn(path,p.diff_policy.protected_paths)
        self.assertIn(".projectctl/\n",files[self.root/".gitignore"])

    def test_build_outputs_does_not_write_to_fixture(self):
        cfg=ProjectConfig(project=ProjectIdentity(id="d2",name="d2"))
        mod.build_outputs(self.root,cfg.model_dump(mode="json"),".dolt/\n")
        self.assertEqual(list(self.root.iterdir()),[])

    def test_canonical_task_rejects_claimed_beads_task(self):
        task={"id":"d2ctl-g4q","status":"in_progress","assignee":"other"}
        with patch.object(mod,"run",return_value=SimpleNamespace(stdout=json.dumps([task]))):
            with self.assertRaisesRegex(ValueError,"claimed/closed"):
                mod.canonical_task(self.root,mod.TASK)

    def test_preview_does_not_call_apply(self):
        dummy={self.root/"example.txt":"test"}
        summary={"candidate_sha256":{"example.txt":"abc"}}
        buffer=io.StringIO()
        env={"PROJECTCTL_HOME":str(self.root)}
        args=["d2_freeze_policy","--repo",str(self.root),"--preview"]
        with (patch.dict("os.environ",env),
              patch.object(sys,"argv",args),
              patch.object(mod,"prepare",return_value=(dummy,summary)),
              patch.object(mod,"apply",side_effect=AssertionError("Preview must not write")),
              contextlib.redirect_stdout(buffer)):
            self.assertEqual(mod.main(),0)
        self.assertEqual(json.loads(buffer.getvalue())["status"],
                         "D2_POLICY_PREVIEW_PASS__NO_FILES_WRITTEN")
        self.assertEqual(list(self.root.iterdir()),[])

    def test_apply_requires_explicit_ack(self):
        err=io.StringIO()
        args=["d2_freeze_policy","--repo",str(self.root),"--apply-and-freeze"]
        with patch.object(sys,"argv",args),contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as exc:
                mod.main()
        self.assertEqual(exc.exception.code,2)
        self.assertIn("ack-local-commit",err.getvalue())

    def test_unexpected_source_root_rejected_before_writes(self):
        with self.assertRaises(ValueError):
            mod.prepare(self.root, self.root, self.root)
        self.assertEqual(list(self.root.iterdir()),[])


if __name__ == "__main__":
    unittest.main()
