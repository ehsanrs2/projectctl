from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_fixture
import preflight


class D0ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='projectctl-d0-tests-')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'fixtures'
        self.output.mkdir()

    def fixture(self, name: str) -> Path:
        path = self.output / name
        build_fixture.build(path, output_root=self.output)
        return path

    def test_preflight_schema_and_zero_inference(self):
        report = preflight.inspect()
        self.assertEqual(report['schema'], 'projectctl.dogfooding_d0_preflight.v2')
        self.assertEqual(report['status'], 'D1_NO_GO')
        self.assertEqual(report['mode'], 'offline_read_only_zero_inference')
        for attr in ('secrets_read', 'network_used', 'projectctl_state_mutated'):
            self.assertFalse(report['isolation'][attr])
        self.assertIn('SDK_MODEL_RUNTIME_UNVERIFIED',
                      {i['code'] for i in report['pending_d1_gates']})
        json.dumps(report)

    def test_fixture_builder_reproduces_clean_local_baseline(self):
        first = self.fixture('arm-a')
        second = self.fixture('arm-b')
        def head(p):
            return subprocess.run(['git', '-C', str(p), 'rev-parse', 'HEAD'],
                                  check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(head(first), head(second))
        self.assertEqual((first/'POLICY.md').read_bytes(), (second/'POLICY.md').read_bytes())
        tests = (first / 'test_user_id.py').read_text()
        self.assertIn('ÄAÉB', tests)
        self.assertIn('internal_whitespace', tests)
        for repo in (first, second):
            for args in (['status', '--porcelain'], ['remote']):
                r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                                   text=True, check=True)
                self.assertEqual(r.stdout, '')

    def test_builder_refuses_source_checkout_and_ancestor(self):
        for root in (build_fixture.SOURCE_CHECKOUT, build_fixture.SOURCE_CHECKOUT.parent):
            with self.assertRaises(ValueError):
                build_fixture.build(root / 'forbidden', output_root=root)
        self.assertFalse((build_fixture.SOURCE_CHECKOUT / 'forbidden').exists())

    def test_builder_refuses_existing_destination_without_delete(self):
        path = self.output / 'already-exists'
        path.mkdir()
        marker = path / 'sentinel.txt'
        marker.write_text('preserve', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            build_fixture.build(path, output_root=self.output)
        self.assertEqual(marker.read_text(), 'preserve')

    def test_builder_refuses_symlink_root_and_destination(self):
        link = Path(self.temp.name) / 'linked'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            build_fixture.build(link / 'new', output_root=link)
        dst = self.output / 'dangling'
        dst.symlink_to(self.output / 'missing')
        with self.assertRaises(FileExistsError):
            build_fixture.build(dst, output_root=self.output)

    def test_builder_refuses_nested_git(self):
        first = self.fixture('arm-a')
        with self.assertRaises(ValueError):
            build_fixture.build(first / 'nested', output_root=first)

    def test_preflight_reports_cleanliness_without_repo_path(self):
        repo = self.fixture('clean-repo')
        clean = preflight.inspect(repo)
        self.assertTrue(clean['repository']['is_git'])
        self.assertTrue(clean['repository']['clean'])
        self.assertFalse(clean['repository']['has_remote'])
        self.assertNotIn(str(repo), json.dumps(clean))
        (repo / 'untracked.txt').write_text('dirty', encoding='utf-8')
        dirty = preflight.inspect(repo)
        self.assertFalse(dirty['repository']['clean'])
        self.assertIn('REPO_DIRTY', {i['code'] for i in dirty['pending_d1_gates']})

    def test_preflight_uses_projectctl_version_subcommand(self):
        calls = []
        def mock_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout='0.41.0\n', stderr='')
        with patch.object(preflight.shutil, 'which', return_value='/mock/projectctl'), \
             patch.object(preflight.subprocess, 'run', side_effect=mock_run):
            self.assertEqual(preflight._version('projectctl', ['version'])['version'], '0.41.0')
        self.assertEqual(calls[0], ['/mock/projectctl', 'version'])

    def test_beads_version_probe_disables_telemetry(self):
        captured = []
        def mock_run(argv, **kwargs):
            captured.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout='bd version 1.3.1\\n', stderr='')
        with patch.object(preflight.shutil, 'which', return_value='/mock/bd'), \\
             patch.object(preflight.subprocess, 'run', side_effect=mock_run):
            result = preflight._version('bd', ['version'])
        self.assertTrue(result['available'])
        self.assertEqual(captured[0][0], ['/mock/bd', 'version'])
        env = captured[0][1]['env']
        self.assertEqual(env['BD_DISABLE_METRICS'], '1')
        self.assertEqual(env['DO_NOT_TRACK'], '1')
        self.assertEqual(env['DOLT_DISABLE_EVENT_FLUSH'], '1')

    def test_environment_ready_does_not_claim_d1_ready(self):
        repo = self.fixture('clean')
        good = {'available': True, 'version': 'ok'}
        with patch.object(preflight, '_version', return_value=good), \
             patch.object(preflight, '_package_version', return_value='0.160.0'), \
             patch.dict(os.environ, {'PROJECTCTL_HOME': '/external/unused'}, clear=False):
            report = preflight.inspect(repo)
        self.assertEqual(report['environment_status'], 'READY_FOR_RUNTIME_PROBE')
        self.assertEqual(report['environment_blockers'], [])
        self.assertEqual(report['status'], 'D1_NO_GO')
        self.assertIn('SDK_MODEL_RUNTIME_UNVERIFIED',
                      {i['code'] for i in report['pending_d1_gates']})

    def test_missing_tool_is_real_environment_blocker(self):
        def which(binary, args):
            return {'available': binary != 'bd', 'version': 'ok'}
        with patch.object(preflight, '_version', side_effect=which), \
             patch.object(preflight, '_package_version', return_value='0.160.0'):
            report = preflight.inspect()
        self.assertEqual(report['environment_status'], 'BLOCKED')
        self.assertIn('BLOCKED_TASK_AUTHORITY',
                      {i['code'] for i in report['environment_blockers']})


if __name__ == '__main__':
    unittest.main()
