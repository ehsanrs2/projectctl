import unittest
from module import sanitize_trace

class TestSanitize(unittest.TestCase):
    def test_top_level(self):
        self.assertEqual(sanitize_trace({'token':'secret','event':'ok'}), {'event':'ok'})
    def test_list(self):
        self.assertEqual(sanitize_trace(['fine',3]), ['fine',3])
if __name__ == '__main__': unittest.main()
