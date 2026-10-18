#!/usr/bin/env python3
"""Compile real reviewer outputs into a human-only review worksheet.

Never opens the hidden oracle. This creates no scored outcome.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('outputs',nargs='+',type=Path,help='Pilot output directories (one or more batches)')
    p.add_argument('--out',type=Path,required=True,help='Fresh markdown file for independent reviewer')
    a=p.parse_args()
    if a.out.exists(): raise SystemExit('Refusing to overwrite review worksheet')
    data=[]
    for directory in a.outputs:
        for m in sorted((directory/'results').glob('*/run_metadata.json')):
            record=json.loads(m.read_text())
            final=m.parent/'final.json'
            if not record.get('report_valid') or not final.is_file():continue
            r=json.loads(final.read_text())
            data.append((record,r))
    lines=['# Review adjudication queue — UNJUDGED','',
           'These are **unverified agent claims**. No oracle was used to construct this file.',
           'An independent adjudicator must test each reproduction and later assign gold match, FP, or unsupported.',
           'Do not send this file or the gold oracle to model reviewers.','']
    for record,report in sorted(data,key=lambda t:(t[0]['case_id'],t[0]['arm'])):
        lines.extend([f"## {record['case_id']} — {record['arm']}",'',
                      f"CLI: `{record['cli_version']}` | Model: `{record['model']}` | Qualified tool-free: `{not bool(record['protocol_violations'])}`",''])
        if not report['findings']:
            lines.extend(['No candidate findings. Human judge: confirm false negatives against gold after all model runs.',''])
        for finding in report['findings']:
            lines.extend([f"### {finding['finding_id']} — {finding['severity']}",
                          f"Location: `{finding['location']}`",'',
                          f"Claim: {finding['claim']}",'',
                          f"Reproduction: {finding['reproduction']}",'',
                          '**Adjudicator decision:** [ ] TP [ ] FP [ ] unsupported — evidence: _____',''])
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'unjudged_runs':len(data),'worksheet':str(a.out)}))
if __name__=='__main__':main()
