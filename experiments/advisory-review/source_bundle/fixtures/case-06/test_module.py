import unittest
from module import validate_transition

class TestTransitions(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_transition('CLAIMED','CLAIMED','RUNNING'),'RUNNING')
    def test_wrong_expected(self):
        with self.assertRaises(ValueError):
            validate_transition('CLAIMED','RUNNING','RUNNING')
    def test_invalid_edge(self):
        with self.assertRaises(ValueError):
            validate_transition('RUNNING','RUNNING','READY_TO_INTEGRATE')
if __name__=='__main__': unittest.main()
