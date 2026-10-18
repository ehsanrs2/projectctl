from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from score_reports import score,ROOT
class TestScore(unittest.TestCase):
    def test_empty_reports(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('{"runs":[]}')
            self.assertEqual(score(p),0)
    def test_matching(self):
        e=[]
        for arm in ['A-baseline','B-gstack-inspired','C-superpowers-inspired']:
            e.append({'arm':arm,'case_id':'case-01','repetition':1,'detected_gold_ids':['G01'] if arm=='B-gstack-inspired' else [],'false_positive_count':0,'protocol_violation_count':0,'wall_seconds':10,'input_tokens':200,'output_tokens':100})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text(json.dumps({'runs':e}))
            self.assertEqual(score(p),0)
    def test_reject_fake_issue(self):
        e=[{'arm':'A-baseline','case_id':'case-05','repetition':1,'detected_gold_ids':['G999'],'false_positive_count':0,'protocol_violation_count':0}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text(json.dumps({'runs':e}))
            with self.assertRaises(ValueError):score(p)
if __name__=='__main__': unittest.main()
