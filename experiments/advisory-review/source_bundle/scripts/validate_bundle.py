#!/usr/bin/env python3
"""Offline structural checks; fixture tests run only with --run-fixture-tests."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
EXPECTED = [f"case-{x:02}" for x in range(1,7)]

def main() -> int:
    p=argparse.ArgumentParser();p.add_argument('--run-fixture-tests', action='store_true');args=p.parse_args()
    oracle=json.loads((ROOT/'oracle/gold.json').read_text())
    assert sorted(oracle['cases'])==EXPECTED
    assert sum(len(v['issues']) for v in oracle['cases'].values())==4
    for c in EXPECTED:
        base=ROOT/'fixtures'/c
        assert all((base/n).is_file() for n in ['SPEC.md','case.json','module.py','test_module.py']),c
        config=json.loads((base/'case.json').read_text());assert config['case_id']==c
        assert 'G01' not in (base/'SPEC.md').read_text()
        if args.run_fixture_tests:
            with tempfile.TemporaryDirectory(prefix='pctl-p0-fixture-') as d:
                temp=Path(d)
                for n in ['SPEC.md','case.json','module.py','test_module.py']:
                    shutil.copy2(base/n,temp/n)
                r=subprocess.run([sys.executable,'-m','unittest','discover','-p','test_module.py','-v'],cwd=temp,capture_output=True,text=True,timeout=30)
                if r.returncode:
                    print(f'{c} FAILED:\n{r.stdout}\n{r.stderr}',file=sys.stderr);return 2
                print(f'{c}: PASS')
    for n in ['advisory_report.v0.schema.json','skill_inventory.v0.schema.json']:
        s=json.loads((ROOT/'schemas'/n).read_text());assert s['additionalProperties'] is False
    print('Bundle structure: PASS; gold issue count: 4; clean cases: 2')
    return 0
if __name__=='__main__': raise SystemExit(main())
