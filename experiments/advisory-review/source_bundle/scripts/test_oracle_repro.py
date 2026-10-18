"""Adjudicator-only demonstrations of deliberately seeded defects.

NEVER put this file or its output in a blind reviewer workspace.
"""
from __future__ import annotations
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def load(case):
    path=ROOT/'fixtures'/case/'module.py'
    spec=importlib.util.spec_from_file_location(f'private_{case}',path)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class TestGoldReproduction(unittest.TestCase):
    def test_g01_string_prefix_sibling(self):
        m=load('case-01')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo';root.mkdir()
            outside=m.resolve_repo_path(str(root),'../repo2/escape.txt')
            self.assertFalse(outside.is_relative_to(root))
    def test_g02_nested_secret(self):
        m=load('case-02')
        self.assertEqual(m.sanitize_trace({'nested':{'token':'s'}}),{'nested':{'token':'s'}})
    def test_g03_input_order_dependency(self):
        m=load('case-03')
        b={'id':'b','priority':3,'ready':True};a={'id':'a','priority':3,'ready':True}
        self.assertEqual(m.select_ready([b,a])['id'],'b')
        self.assertEqual(m.select_ready([a,b])['id'],'a')
    def test_g04_unverified_integration(self):
        m=load('case-04')
        got=m.integration_decision({'status':'implemented','candidate_digest':'sha256:a'}, {'passed':False,'candidate_digest':'sha256:b'})
        self.assertEqual(got,'READY_TO_INTEGRATE')
    def test_clean_canonical(self):
        m=load('case-05');self.assertEqual(m.canonical_json({'b':2,'a':1}),b'{"a":1,"b":2}')
    def test_clean_transitions(self):
        m=load('case-06');self.assertEqual(m.validate_transition('CLAIMED','CLAIMED','RUNNING'),'RUNNING')
        with self.assertRaises(ValueError):m.validate_transition('CLAIMED','RUNNING','RUNNING')
if __name__=='__main__':unittest.main()
