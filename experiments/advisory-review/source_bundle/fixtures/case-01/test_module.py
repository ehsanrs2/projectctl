import tempfile
import unittest
from pathlib import Path
from module import resolve_repo_path

class TestContainment(unittest.TestCase):
    def test_inside_and_simple_parent_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'repo'; root.mkdir()
            assert resolve_repo_path(str(root), 'src/main.py') == (root / 'src/main.py').resolve()
            with self.assertRaises(ValueError):
                resolve_repo_path(str(root), '../outside/file')
if __name__ == '__main__': unittest.main()
