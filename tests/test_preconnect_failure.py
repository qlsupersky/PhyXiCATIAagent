"""Only a bound failure before CATIA object acquisition is known no-dispatch."""
import json
import test_terminal_failure

class PreconnectFailure(test_terminal_failure.TerminalFailure):
    def setUp(self):
        super().setUp()
        self.rows = [
            {'name':'before_call','detail':{'call':'Marshal.GetActiveObject'}},
            {'name':'probe_error','detail':{'type':'System.Runtime.InteropServices.COMException','hresult':-2147221021}},
            {'name':'execution_finished','detail':{'run_id':self.job,
                'macro_sha256':self.manifest['macro_sha256'], 'checks_sha256':self.manifest['checks_sha256'],
                'com_return_observed':False,'script_error_returned':False,'outcome':'UNKNOWN'}}]
        self.exit = {'child_return_observed':True,'returncode':2}

    # Parent tests assume validation semantics; only inherit its fixture helpers.
    test_known_validation_failure_releases_without_approval = None
    test_unknown_or_unbound_terminal_does_not_release = None
    test_crash_after_exit_automatically_reconciles = None
    test_log_changes_prevent_auto_reconciliation = None

    def test_no_object_acquired_is_known_failure(self):
        r=self.service.terminal_failure(self.job,self.claim['owner'],self.manifest,self.rows,self.exit)
        self.assertEqual(r['reason'],'catia_not_running_before_dispatch')
        self.assertFalse(r['CAD_dispatch'])
        self.assertEqual(self.service.snapshot()['status'],'IDLE')

    def test_rpc_dispatch_extra_events_or_bad_binding_remain_unknown(self):
        for kind in ['rpc','dispatch','extra','binding','object','child','tail']:
            rows=json.loads(json.dumps(self.rows));ex=dict(self.exit)
            if kind=='rpc':rows[1]['detail']['hresult']=-2147023174
            if kind=='dispatch':rows[0]['detail']['call']='SystemService.ExecuteScript'
            if kind=='extra':rows.insert(1,{'name':'baseline_inventory','detail':{'count':0}})
            if kind=='binding':rows[-1]['detail']['macro_sha256']='wrong'
            if kind=='object':rows[-1]['detail']['com_return_observed']=True
            if kind=='child':ex['child_return_observed']=False
            if kind=='tail':rows.append({'name':'untrusted_tail'})
            self.assertIsNone(self.service.terminal_failure_result(self.job,self.manifest,rows,ex),kind)

    def test_restart_reconciliation_requires_hash_bound_log(self):
        from native_contract import sha
        from native_service import NativeService
        folder=self.service.folder(self.job);log=folder/'execute.stdout.jsonl'
        log.write_text('\n'.join(json.dumps(r) for r in self.rows)+'\n',encoding='utf8')
        ex={**self.exit,'bridge_sha256':self.manifest['bridge_sha256'],'stdout_sha256':sha(log.read_bytes())}
        (folder/'bridge-exit.json').write_text(json.dumps(ex),encoding='utf8')
        self.service.finish(self.job,self.claim['owner'])
        service=NativeService(self.root,self.root/'gate.sqlite')
        self.assertEqual(service.snapshot()['status'],'IDLE')
        self.assertEqual(service.job(self.job)['state'],'FAILED')
