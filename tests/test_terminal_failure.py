"""Known failure releases queue, unknown work and duplicates remain distinct."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from native_contract import sha
from native_service import NativeService
from native_gate import GateBlocked
from test_native_core import fixture, MACRO

class TerminalFailure(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ['PHYXI_TEST_WORK'])
        self.root=Path(self.temp.name)
        self.service,self.job=fixture(self.root)
        self.service.reserve(self.job)
        self.claim=self.service.claim(self.job,MACRO)
        self.manifest=self.claim['manifest']
        self.rows=[{'name':'com_return_observed','detail':{'value':None}},
                   {'name':'independent_readback','detail':{'passed':False,'volume_match':False}},
                   {'name':'validation_failed','detail':{'passed':False}},
                   {'name':'execution_finished','detail':{'run_id':self.job,'macro_sha256':self.manifest['macro_sha256'],
                    'checks_sha256':self.manifest['checks_sha256'],'com_return_observed':True,'outcome':'FAILED'}}]
        self.exit={'child_return_observed':True,'returncode':3}

    def tearDown(self):self.temp.cleanup()

    def test_known_validation_failure_releases_without_approval(self):
        result=self.service.terminal_failure(self.job,self.claim['owner'],self.manifest,self.rows,self.exit)
        self.assertEqual(result['state'],'FAILED')
        self.assertFalse(result['passed'])
        self.assertEqual(self.service.snapshot()['status'],'IDLE')
        self.assertEqual(self.service.job(self.job)['state'],'FAILED')
        # Replaying a failed request returns the failure, never another dispatch.
        with patch('native_service.subprocess.run',side_effect=AssertionError('no replay')):
            cached=self.service.run(self.job,MACRO)
        self.assertTrue(cached['cached_no_CAD_dispatch'])
        self.assertEqual(cached['state'],'FAILED')
        token=self.service.acquire('a corrected new operation')
        self.service.complete(token,{'fixture':True})

    def test_unknown_or_unbound_terminal_does_not_release(self):
        for mutate in ['child','run','hash','com','marker']:
            rows=json.loads(json.dumps(self.rows));record=dict(self.exit)
            if mutate=='child':record['child_return_observed']=False
            if mutate=='run':rows[-1]['detail']['run_id']='unrelated'
            if mutate=='hash':rows[-1]['detail']['macro_sha256']='bad'
            if mutate=='com':rows[-1]['detail']['com_return_observed']=False
            if mutate=='marker':rows.pop()
            self.assertIsNone(self.service.terminal_failure(self.job,self.claim['owner'],self.manifest,rows,record))
        self.assertEqual(self.service.snapshot()['status'],'RUNNING')

    def test_crash_after_exit_automatically_reconciles(self):
        folder=self.service.folder(self.job)
        log=folder/'execute.stdout.jsonl'
        log.write_text('\n'.join(json.dumps(r) for r in self.rows)+'\n',encoding='utf-8')
        record={**self.exit,'bridge_sha256':self.manifest['bridge_sha256'],'stdout_sha256':sha(log.read_bytes())}
        (folder/'bridge-exit.json').write_text(json.dumps(record),encoding='utf-8')
        self.service.finish(self.job,self.claim['owner'])
        recovered=NativeService(self.root,self.root/'gate.sqlite')
        self.assertEqual(recovered.snapshot()['status'],'IDLE')
        self.assertEqual(recovered.job(self.job)['state'],'FAILED')

    def test_log_changes_prevent_auto_reconciliation(self):
        folder=self.service.folder(self.job);log=folder/'execute.stdout.jsonl'
        log.write_text('\n'.join(json.dumps(r) for r in self.rows)+'\n',encoding='utf-8')
        record={**self.exit,'bridge_sha256':self.manifest['bridge_sha256'],'stdout_sha256':sha(log.read_bytes())}
        (folder/'bridge-exit.json').write_text(json.dumps(record),encoding='utf-8')
        log.write_text(log.read_text()+'\n',encoding='utf-8')
        self.service.finish(self.job,self.claim['owner'])
        recovered=NativeService(self.root,self.root/'gate.sqlite')
        self.assertEqual(recovered.snapshot()['status'],'FROZEN')

if __name__=='__main__':unittest.main(verbosity=2)
