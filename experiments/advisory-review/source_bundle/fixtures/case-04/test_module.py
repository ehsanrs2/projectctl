import unittest
from module import integration_decision

class TestGate(unittest.TestCase):
    def test_happy_path(self):
        w={'status':'implemented','candidate_digest':'sha256:x'}
        v={'passed': True,'candidate_digest':'sha256:x'}
        self.assertEqual(integration_decision(w,v),'READY_TO_INTEGRATE')
    def test_not_implemented(self):
        self.assertEqual(integration_decision({'status':'failed'},{'passed':True}),'REJECTED')
if __name__ == '__main__': unittest.main()
