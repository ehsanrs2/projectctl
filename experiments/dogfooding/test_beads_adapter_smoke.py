"""Zero-mutation guard tests for the opt-in Beads smoke runner."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import beads_adapter_smoke as smoke


class BeadsSmokeToolTests(unittest.TestCase):
    def test_not_run_without_explicit_ack(self):
        sink = io.StringIO()
        with patch('sys.argv', ['beads_adapter_smoke.py', '--execute']), contextlib.redirect_stdout(sink):
            code = smoke.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(sink.getvalue())['status'], 'NOT_RUN')

    def test_missing_binary_blocks_before_state_change(self):
        sink = io.StringIO()
        with (patch('sys.argv', ['beads_adapter_smoke.py', '--execute', '--ack-temporary-repo']),
              patch.object(smoke.shutil, 'which', side_effect=lambda name: None if name == 'bd' else '/usr/bin/git'),
              contextlib.redirect_stdout(sink)):
            code = smoke.main()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(sink.getvalue())['status'], 'BLOCKED_DEPENDENCY')


if __name__ == '__main__':
    unittest.main()
