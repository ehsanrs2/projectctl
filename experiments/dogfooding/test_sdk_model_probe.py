"""Offline contract tests; never connect to Codex or incur model usage."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdk_model_probe as mod


class SDKModelProbeTests(unittest.TestCase):
    def test_requires_both_explicit_flags(self):
        for flags in ([], ['--execute'], ['--ack-paid']):
            output = io.StringIO()
            with (patch.object(sys, 'argv', ['probe.py', *flags]),
                  patch.object(mod, 'execute_probe', side_effect=AssertionError('should never invoke')),
                  contextlib.redirect_stdout(output)):
                self.assertEqual(mod.main(), 0)
            self.assertEqual(json.loads(output.getvalue())['status'], 'NOT_RUN')

    def test_sdk_version_mismatch_prevents_model_call(self):
        output = io.StringIO()
        with (patch.object(sys, 'argv', ['probe.py', '--execute', '--ack-paid']),
              patch.object(mod.importlib.metadata, 'version', return_value='other'),
              patch.object(mod, 'execute_probe', side_effect=AssertionError('should never invoke')),
              contextlib.redirect_stdout(output)):
            self.assertEqual(mod.main(), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'SDK_VERSION_MISMATCH')

    def test_explicit_authorization_dispatches_exactly_once(self):
        output = io.StringIO()
        with (patch.object(sys, 'argv', ['probe.py', '--execute', '--ack-paid']),
              patch.object(mod.importlib.metadata, 'version', return_value=mod.PINNED_SDK),
              patch.object(mod, 'execute_probe', return_value={'status': 'SDK_MODEL_PROBE_PASS'}) as worker,
              contextlib.redirect_stdout(output)):
            self.assertEqual(mod.main(), 0)
        worker.assert_called_once_with()
        self.assertEqual(json.loads(output.getvalue())['status'], 'SDK_MODEL_PROBE_PASS')


if __name__ == '__main__':
    unittest.main()
