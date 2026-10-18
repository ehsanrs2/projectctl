#!/usr/bin/env python3
"""Score *manually adjudicated* review results; makes no LLM correctness judgments."""
from __future__ import annotations
import argparse, json, statistics, sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
ARMS=('A-baseline','B-gstack-inspired','C-superpowers-inspired')
def score(path:Path):
    gold=json.loads((ROOT/'oracle/gold.json').read_text())['cases']
    entries=json.loads(path.read_text())['runs']; seen=set();byarm=defaultdict(list)
    for e in entries:
        key=(e['arm'],e['case_id'],e['repetition'])
        if key in seen:raise ValueError(f'duplicate {key}')
        seen.add(key)
        if e['arm'] not in ARMS or e['case_id'] not in gold or type(e['repetition']) is not int or e['repetition']<1:raise ValueError('bad arm/case/repetition')
        valid={i['id'] for i in gold[e['case_id']]['issues']}
        ids=e['detected_gold_ids']
        if len(ids)!=len(set(ids)) or any(i not in valid for i in ids): raise ValueError(f'unknown gold detection in {key}')
        if any(type(e[x]) is not int or e[x]<0 for x in ['false_positive_count','protocol_violation_count']):raise ValueError('invalid count')
        for x in ['wall_seconds','input_tokens','output_tokens']:
            if e.get(x) is not None and (type(e[x]) not in (int,float) or e[x]<0): raise ValueError('invalid metric '+x)
        byarm[e['arm']].append(e)
    allpairs=defaultdict(set)
    for arm,rs in byarm.items():
        for e in rs:allpairs[(e['case_id'],e['repetition'])].add(arm)
    matched={k for k,v in allpairs.items() if v==set(ARMS)}
    print(f'Matched case x repetition groups: {len(matched)}; unpaired groups excluded: {len(allpairs)-len(matched)}')
    data={}
    for arm in ARMS:
        rs=[e for e in byarm[arm] if (e['case_id'],e['repetition']) in matched]
        gold_total=sum(len(gold[e['case_id']]['issues']) for e in rs)
        tp=sum(len(e['detected_gold_ids']) for e in rs)
        fp=sum(e['false_positive_count'] for e in rs)
        critical_gold=sum(1 for e in rs for z in gold[e['case_id']]['issues'] if z['severity']=='critical')
        critical_hits=sum(1 for e in rs for z in gold[e['case_id']]['issues'] if z['severity']=='critical' and z['id'] in e['detected_gold_ids'])
        def summ(k):
            vals=[e[k] for e in rs if e.get(k) is not None]
            return round(sum(vals),2) if len(vals)==len(rs) and rs else None
        data[arm]={'runs':len(rs),'true_positive':tp,'false_positive':fp,'gold_total':gold_total,
                  'recall':round(tp/gold_total,4) if gold_total else None,
                  'precision':round(tp/(tp+fp),4) if tp+fp else None,
                  'critical_detected':critical_hits,'critical_gold':critical_gold,
                  'protocol_violations':sum(e['protocol_violation_count'] for e in rs),
                  'total_seconds':summ('wall_seconds'),'total_tokens':(sum(e['input_tokens']+e['output_tokens'] for e in rs) if rs and all(e.get('input_tokens') is not None and e.get('output_tokens') is not None for e in rs) else None)}
    print(json.dumps({'interpretation':'Exploratory paired pilot; not project acceptance evidence','metrics':data},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('adjudicated_runs_json',type=Path);a=p.parse_args()
    try:raise SystemExit(score(a.adjudicated_runs_json))
    except (ValueError,KeyError,TypeError,AssertionError) as exc:print(f'INVALID: {exc}',file=sys.stderr);raise SystemExit(2)
