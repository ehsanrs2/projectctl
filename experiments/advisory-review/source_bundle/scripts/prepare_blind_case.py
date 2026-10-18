#!/usr/bin/env python3
"""Copy a single synthetic fixture without the private gold answers."""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
PARSER = argparse.ArgumentParser()
PARSER.add_argument('case_id', choices=[f'case-{i:02}' for i in range(1,7)])
PARSER.add_argument('destination', help='Must not exist; use a new temp/workspace path')

def main() -> int:
    a=PARSER.parse_args(); src=ROOT/'fixtures'/a.case_id; dest=Path(a.destination).expanduser().resolve(strict=False)
    if dest.exists(): print('REFUSED: destination exists',file=sys.stderr);return 2
    if ROOT==dest or ROOT in dest.parents or dest in ROOT.parents:
        print('REFUSED: destination overlaps evaluator bundle or its ancestors',file=sys.stderr);return 2
    dest.mkdir(parents=True,exist_ok=False)
    for filename in ['SPEC.md','module.py','test_module.py','case.json']:
        shutil.copyfile(src/filename,dest/filename)
    print(json.dumps({'case_id':a.case_id,'output':str(dest),'oracle_copied':False}))
    return 0
if __name__=='__main__':raise SystemExit(main())
