import unittest
from module import select_ready

class TestPick(unittest.TestCase):
    def test_no_ready(self):
        self.assertIsNone(select_ready([{'id':'a','priority':1,'ready':False}]))
    def test_highest_priority(self):
        self.assertEqual(select_ready([{'id':'a','priority':1,'ready':True},{'id':'b','priority':3,'ready':True}])['id'],'b')
if __name__ == '__main__': unittest.main()
