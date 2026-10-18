import math
import unittest
from module import canonical_json

class TestCanonical(unittest.TestCase):
    def test_stability(self):
        self.assertEqual(canonical_json({'b':2,'a':1}),b'{"a":1,"b":2}')
        self.assertEqual(canonical_json({'a':1,'b':2}),b'{"a":1,"b":2}')
    def test_nonfinite_refused(self):
        with self.assertRaises(ValueError):canonical_json({'x':math.inf})
if __name__=='__main__': unittest.main()
