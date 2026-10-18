from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from codex_pilot_runner import (ARMS,JOBS,build_prompt,inspect_events,prepare,validate_report,codex_args,strict_model_schema,strict_schema_for_job,expected_run_id)
BUNDLE=ROOT/'source_bundle'
SCHEMA=BUNDLE/'schemas'/'advisory_report.v0.schema.json'

class PilotTests(unittest.TestCase):
    def test_nine_jobs_complete_per_case(self):
        self.assertEqual(len(JOBS),9)
        self.assertEqual(set(c for c,_ in JOBS),{'case-01','case-04','case-05'})
        for case in ('case-01','case-04','case-05'):
            self.assertEqual(set(a for c,a in JOBS if c==case),set(ARMS))

    def test_prompt_excludes_gold_and_matches_arm(self):
        for case,arm in JOBS:
            p=build_prompt(BUNDLE,case,arm)
            self.assertIn(case,p)
            self.assertIn('Set run_id exactly to "'+expected_run_id(case,arm)+'"',p)
            self.assertNotIn('G01',p)
            self.assertNotIn('G04',p)
            self.assertNotIn('gold.json',p)
            self.assertIn('--- BEGIN UNTRUSTED SPEC.md ---',p)
            self.assertIn('do not inspect the filesystem',p)

    def test_preparation_no_inference(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'work'
            rows=prepare(BUNDLE,out,None,'medium')
            self.assertEqual(len(rows),9)
            p=json.loads((out/'plan.json').read_text())
            self.assertEqual(p['real_model_invocations'],0)
            self.assertFalse((out/'oracle').exists())
            self.assertEqual(len(list((out/'prompts').glob('*.txt'))),9)
            self.assertEqual(len(list((out/'wire_schemas').glob('*.json'))),9)
            with self.assertRaises(ValueError):prepare(BUNDLE,out,None,'medium')
            with self.assertRaises(ValueError):prepare(BUNDLE,BUNDLE/'inside',None,'medium')

    def test_schema_validates_and_rejects_extra(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'final.json'
            good={'schema_version':'research.advisory.v0','run_id':'case-05-a-baseline','case_id':'case-05',
                  'arm':'A-baseline','reviewer':'mock','findings':[],'protocol_violations':[],
                  'input_tokens':None,'output_tokens':None,'wall_seconds':None}
            p.write_text(json.dumps(good))
            self.assertEqual(validate_report(p,SCHEMA,'case-05','A-baseline')['findings'],[])
            good['hidden_field']=123;p.write_text(json.dumps(good))
            with self.assertRaises(Exception):validate_report(p,SCHEMA,'case-05','A-baseline')
            del good['hidden_field'];good['arm']='B-gstack-inspired';p.write_text(json.dumps(good))
            with self.assertRaises(ValueError):validate_report(p,SCHEMA,'case-05','A-baseline')
            good['arm']='A-baseline';good['run_id']='';p.write_text(json.dumps(good))
            with self.assertRaises(Exception):validate_report(p,SCHEMA,'case-05','A-baseline')
            good['run_id']='other-nonempty-id';p.write_text(json.dumps(good))
            with self.assertRaises(ValueError):validate_report(p,SCHEMA,'case-05','A-baseline')


    def test_codex_strict_schema_recursive_and_local_semantics(self):
        original=json.loads(SCHEMA.read_text())
        strict=strict_model_schema(original)
        self.assertEqual(set(strict['required']),set(strict['properties']))
        self.assertFalse(strict['additionalProperties'])
        nested=strict['properties']['findings']['items']
        self.assertEqual(set(nested['required']),set(nested['properties']))
        self.assertFalse(nested['additionalProperties'])
        self.assertNotIn('$schema',strict)
        self.assertNotIn('minLength',strict['properties']['run_id'])
        for metric in ('wall_seconds','input_tokens','output_tokens'):
            self.assertIn(metric,strict['required'])
            self.assertIn('null',strict['properties'][metric]['type'])
        good={'schema_version':'research.advisory.v0','run_id':'r-1','case_id':'case-05',
              'arm':'A-baseline','reviewer':'mock','findings':[],
              'protocol_violations':[],'notes':'',
              'wall_seconds':None,'input_tokens':None,'output_tokens':None}
        import jsonschema
        jsonschema.Draft202012Validator(strict).validate(good)
        jsonschema.Draft202012Validator(original).validate(good)
        del good['notes']
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(strict).validate(good)

    def test_strict_schema_derived_without_mutating_frozen_bundle(self):
        import hashlib
        original_hash=hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'work'
            prepare(BUNDLE,out,'gpt-6-luna','medium')
            plan=json.loads((out/'plan.json').read_text())
            strict_path=out/plan['codex_output_schema_file']
            self.assertTrue(strict_path.is_file())
            self.assertEqual(hashlib.sha256(strict_path.read_bytes()).hexdigest(),
                             plan['codex_output_schema_sha256'])
            self.assertEqual(original_hash,plan['canonical_validator_schema_sha256'])
            self.assertEqual(len(list((out/'wire_schemas').glob('*.json'))),9)
            for job in plan['jobs']:
                wire_path=out/job['wire_schema_file']
                self.assertTrue(wire_path.is_file())
                self.assertEqual(hashlib.sha256(wire_path.read_bytes()).hexdigest(),job['wire_schema_sha256'])
                wire=json.loads(wire_path.read_text())
                self.assertEqual(wire['properties']['run_id']['const'],expected_run_id(job['case_id'],job['arm']))
                self.assertEqual(wire['properties']['case_id']['const'],job['case_id'])
                self.assertEqual(wire['properties']['arm']['const'],job['arm'])
                self.assertEqual(wire['required'],list(wire['properties']))
                self.assertFalse(wire['additionalProperties'])
        self.assertEqual(original_hash,hashlib.sha256(SCHEMA.read_bytes()).hexdigest())

    def test_job_specific_wire_schema_forbids_empty_id(self):
        import jsonschema
        general=strict_model_schema(json.loads(SCHEMA.read_text()))
        wire=strict_schema_for_job(general,'case-01','B-gstack-inspired')
        good={'schema_version':'research.advisory.v0',
              'run_id':expected_run_id('case-01','B-gstack-inspired'),
              'case_id':'case-01','arm':'B-gstack-inspired',
              'reviewer':'mock','findings':[],'protocol_violations':[],
              'wall_seconds':None,'input_tokens':None,'output_tokens':None,'notes':''}
        jsonschema.Draft202012Validator(wire).validate(good)
        good['run_id']=''
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(wire).validate(good)
        good['run_id']='case-01-a-baseline'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(wire).validate(good)

    def test_strict_schema_unknown_keyword_fails_closed(self):
        local=json.loads(SCHEMA.read_text())
        local['properties']['run_id']['oneOf']=[{'type':'string'}]
        with self.assertRaisesRegex(ValueError,'Unsupported schema keyword'):
            strict_model_schema(local)

    def test_codex_paths_are_absolute_even_for_relative_output(self):
        command=codex_args('codex','gpt-6-luna','medium',
                           Path('source_bundle/schemas/wire.json'),
                           Path('output/attempt-1/results/01/final.json'))
        schema=Path(command[command.index('--output-schema')+1])
        result=Path(command[command.index('--output-last-message')+1])
        self.assertTrue(schema.is_absolute(),command)
        self.assertTrue(result.is_absolute(),command)

    def test_flags_and_event_tool_policy(self):
        c=codex_args('codex','test-model','medium',SCHEMA,Path('/tmp/final.json'))
        self.assertIn('read-only',c)
        self.assertIn('--ignore-user-config',c)
        self.assertIn('--ephemeral',c)
        with tempfile.TemporaryDirectory() as td:
            log=Path(td)/'events.jsonl'
            log.write_text('\n'.join((json.dumps({'type':'thread.started'}),
                json.dumps({'type':'item.started','item':{'type':'command_execution'}}),
                json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':22}}))))
            got=inspect_events(log)
            self.assertTrue(got['protocol_violations'])
            self.assertEqual(got['usage_observed']['input_tokens'],100)

    def test_no_paid_execution_without_ack(self):
        with tempfile.TemporaryDirectory() as td:
            cmd=[sys.executable,str(ROOT/'scripts'/'codex_pilot_runner.py'),
                '--bundle',str(BUNDLE),'--out',str(Path(td)/'b'),'--execute',
                '--model','not-a-real-model']
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,2)
            self.assertFalse((Path(td)/'b').exists())

    def test_mock_subprocess_end_to_end_nine(self):
        with tempfile.TemporaryDirectory() as td:
            fake=Path(td)/'codex';out=Path(td)/'out'
            fake.write_text('''#!/usr/bin/env python3
import sys,json,pathlib
args=sys.argv[1:]
if args==['--version']:
 print('codex-mock-0.0-test-only');raise SystemExit(0)
if args[:2]==['exec','--help']:
 print(' '.join(['--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','--json','--output-schema','--output-last-message','--model']));raise SystemExit(0)
msg=sys.stdin.read()
arm=next(a for a in ('A-baseline','B-gstack-inspired','C-superpowers-inspired') if 'Arm: '+a in msg)
case=next(c for c in ('case-01','case-04','case-05') if 'Case: '+c in msg)
schema=pathlib.Path(args[args.index('--output-schema')+1])
assert schema.is_absolute() and schema.is_file(), 'Codex wire schema path must be accessible from isolated cwd'
wire=json.loads(schema.read_text())
assert wire['properties']['case_id']['const']==case
assert wire['properties']['arm']['const']==arm
assert wire['properties']['run_id']['const']==case+'-'+arm.lower()
p=pathlib.Path(args[args.index('--output-last-message')+1])
assert p.is_absolute(), 'Final output path must be absolute'
p.write_text(json.dumps({'schema_version':'research.advisory.v0','run_id':wire['properties']['run_id']['const'],
 'case_id':case,'arm':arm,'reviewer':'MOCK_NOT_A_REAL_REVIEW',
 'findings':[],'protocol_violations':[],
 'wall_seconds':None,'input_tokens':None,'output_tokens':None,'notes':''}))
for e in [{'type':'thread.started'},{'type':'turn.started'},
 {'type':'item.completed','item':{'type':'agent_message','text':'test'}},
 {'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':17}}]:
 print(json.dumps(e))
''')
            fake.chmod(0o700)
            cmd=[sys.executable,str(ROOT/'scripts'/'codex_pilot_runner.py'),
                '--bundle',str(BUNDLE),'--out','out','--execute',
                '--ack-paid','--ack-host-read-risk','--model','mock',
                '--codex-bin',str(fake),'--timeout-seconds','30','--max-paid-runs','9']
            r=subprocess.run(cmd,cwd=td,capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr+' '+r.stdout)
            summary=json.loads((out/'execution_summary.json').read_text())
            self.assertEqual(summary['attempted'],9)
            self.assertEqual(summary['qualified_tool_free'],9)
            self.assertTrue(all(x['model']=='mock' for x in summary['results']))
            self.assertFalse(any(x['findings_claimed'] for x in summary['results']))

if __name__=='__main__':unittest.main()
