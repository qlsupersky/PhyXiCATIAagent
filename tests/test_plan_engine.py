import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plan_engine import PlanEngine, normalize, verify


class Plans(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ['PHYXI_TEST_WORK']); base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base); self.root = Path(self.temp.name)
        self.calls = []
        def dispatch(name, args):
            self.calls.append(name)
            return {'content': [{'type': 'text', 'text': json.dumps({'volume_mm3': 1200})}]}
        def validate(name, args):
            if name not in ('create', 'measure', 'save'): raise ValueError('unknown')
        self.engine = PlanEngine(self.root, self.root / 'gate.sqlite', dispatch, validate)
        self.steps = [{'id': 'create', 'tool': 'create'}, {'id': 'check', 'tool': 'measure', 'expect': [{'path': '/volume_mm3', 'value': 1200, 'tolerance': .01}]}, {'id': 'save', 'tool': 'save'}]

    def tearDown(self): self.temp.cleanup()

    def test_ordered_execution_with_real_return_checks(self):
        result = self.engine.run('operation1', self.steps)
        self.assertEqual(self.calls, ['create', 'measure', 'save'])
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertTrue(result['declared_checks_passed'])
        self.assertFalse(result['geometry_verified'])
        self.assertEqual(result['results'][1]['verification']['checks'][0]['actual'], 1200)
        self.assertEqual(self.engine.gate.snapshot()['status'], 'IDLE')

    def test_finished_duplicate_returns_cache(self):
        self.engine.run('one', self.steps)
        self.assertTrue(self.engine.run('one', self.steps)['cached_no_CAD_dispatch'])
        self.assertEqual(len(self.calls), 3)

    def test_changed_input_rejected(self):
        self.engine.run('one', self.steps)
        with self.assertRaisesRegex(ValueError, 'different input'): self.engine.run('one', self.steps[:1])

    def test_entire_plan_validated_before_dispatch(self):
        with self.assertRaises(ValueError): self.engine.run('one', self.steps + [{'id': 'bad', 'tool': 'not_found'}])
        self.assertEqual(self.calls, [])

    def test_failed_check_stops_remaining_and_releases(self):
        self.steps[1]['expect'][0]['value'] = 900
        result = self.engine.run('one', self.steps)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['skipped_steps'], ['save'])
        self.assertEqual(self.engine.gate.snapshot()['status'], 'IDLE')
        self.assertFalse(result['declared_checks_passed'])

    def test_missing_measurement_does_not_pass(self):
        self.steps[1]['expect'][0]['path'] = '/not_reported'
        result = self.engine.run('one', self.steps)
        self.assertEqual(result['status'], 'FAILED')
        self.assertFalse(result['results'][1]['verification']['checks'][0]['passed'])

    def test_legacy_error_not_classified_success(self):
        self.engine.dispatch = lambda n, a: 'Error: invalid profile'
        result = self.engine.run('one', self.steps)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(self.engine.gate.snapshot()['status'], 'IDLE')

    def test_rpc_failure_freezes_no_replay(self):
        self.engine.dispatch = lambda n, a: {'isError': True, 'structuredContent': {'ok': False, 'code': 'COM_ERROR', 'effects': {'modified': None}}}
        result = self.engine.run('one', self.steps)
        self.assertEqual(result['status'], 'UNCERTAIN')
        self.assertEqual(self.engine.gate.snapshot()['status'], 'FROZEN')
        cached = self.engine.run('one', self.steps)
        self.assertTrue(cached['cached_no_CAD_dispatch'])
        self.assertEqual(self.engine.run('two', self.steps)['status'], 'REJECTED_BUSY')

    def test_bound_returned_automation_failure_releases_but_not_success(self):
        self.engine.dispatch = lambda n,a: {'isError':True,'structuredContent':{'ok':False,'code':'COM_ERROR','message':"(-2147352567, 'SaveAs failed', (0, 'CATIAPartDocument', 'failure', None, 0, -2147467259), None)",'effects':{'modified':None}}}
        result=self.engine.run('one',self.steps)
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(result['completion'],'KNOWN_FINISHED')
        self.assertEqual(self.engine.gate.snapshot()['status'],'IDLE')

    def test_rpc_hresult_overrides_wrapped_automation_error(self):
        value=normalize('tool',{'isError':True,'structuredContent':{'ok':False,'code':'COM_ERROR','message':'-2147467259, RPC_E_DISCONNECTED -2147417848','effects':{'modified':None}}})
        self.assertEqual(value['completion'],'UNCERTAIN')

    def test_no_active_document_query_is_known_precondition_only(self):
        tool='catia_get_active_document_info'
        raw={'isError':True,'structuredContent':{'ok':False,'code':'COM_ERROR','tool':tool,
             'message':'No active document in CATIA. Create or open a document first.',
             'data':{'failure_stage':'execute'},'effects':{'modified':None}}}
        r=normalize(tool,raw)
        self.assertEqual(r['completion'],'KNOWN_FINISHED')
        self.assertFalse(r['effects']['modified'])
        self.assertTrue(r['completion_evidence'])
        self.assertEqual(normalize('catia_pad',raw)['completion'],'UNCERTAIN')
        raw['structuredContent']['message']+=' RPC_E_DISCONNECTED'
        self.assertEqual(normalize(tool,raw)['completion'],'UNCERTAIN')

    def test_restart_reconciles_only_matching_stored_terminal_error(self):
        self.engine.dispatch = lambda n,a: {'isError':True,'structuredContent':{'ok':False,'code':'COM_ERROR','message':'bound HRESULT -2147467259','effects':{'modified':None}}}
        # Simulate the older version's classification; preserve its raw result.
        from plan_engine import normalize as current
        def old(*args):
            result=current(*args);result['completion']='UNCERTAIN';return result
        with patch('plan_engine.normalize',side_effect=old): self.engine.run('old',self.steps)
        self.assertEqual(self.engine.gate.snapshot()['status'],'FROZEN')
        restored=PlanEngine(self.root,self.root/'gate.sqlite',lambda n,a:self.fail('replayed'))
        record=restored.status('old')
        self.assertEqual(record['status'],'FAILED')
        self.assertTrue(record['reconciliation']['no_replay'])
        self.assertEqual(record['results'][0]['completion'],'UNCERTAIN')
        self.assertEqual(restored.gate.snapshot()['status'],'IDLE')

    def test_exact_no_active_sketch_read_is_finished_not_success(self):
        tool='catia_sketch_get_geometry'
        data={'ok':False,'code':'COM_ERROR','tool':tool,
              'message':'No active sketch. Use catia_create_sketch first to open a sketch.',
              'data':{'failure_stage':'execute'},'effects':{'modified':None}}
        raw={'isError':True,'structuredContent':data}
        r=normalize(tool,raw)
        self.assertFalse(r['ok'])
        self.assertEqual(r['completion'],'KNOWN_FINISHED')
        self.assertEqual(r['effects'],{'modified':False})
        self.assertEqual(r['completion_evidence'],{'precondition':'NO_ACTIVE_SKETCH_READ_ONLY'})
        self.assertEqual(normalize('catia_sketch_circle',raw)['completion'],'UNCERTAIN')
        altered=json.loads(json.dumps(raw));altered['structuredContent']['message']+=' extra'
        self.assertEqual(normalize(tool,altered)['completion'],'UNCERTAIN')
        altered=json.loads(json.dumps(raw));altered['structuredContent']['data']={'failure_stage':'unknown'}
        self.assertEqual(normalize(tool,altered)['completion'],'UNCERTAIN')
        altered=json.loads(json.dumps(raw));altered['content']=[{'type':'text','text':'RPC_E_DISCONNECTED -2147417848'}]
        self.assertEqual(normalize(tool,altered)['completion'],'UNCERTAIN')

    def test_no_active_sketch_read_stops_plan_without_freezing_or_replay(self):
        tool='catia_sketch_get_geometry'
        self.engine.validate=lambda n,a:None
        self.engine.dispatch=lambda n,a:{'isError':True,'structuredContent':{
            'ok':False,'code':'COM_ERROR','tool':tool,
            'message':'No active sketch. Use catia_create_sketch first to open a sketch.',
            'data':{'failure_stage':'execute'}}}
        steps=[{'id':'read','tool':tool},{'id':'never','tool':'catia_pad'}]
        r=self.engine.run('no-sketch',steps)
        self.assertEqual(r['status'],'FAILED')
        self.assertEqual(r['skipped_steps'],['never'])
        self.assertEqual(len(r['results']),1)
        self.assertEqual(self.engine.gate.snapshot()['status'],'IDLE')
        self.engine.dispatch=lambda n,a:self.fail('must not replay')
        self.assertTrue(self.engine.run('no-sketch',steps)['cached_no_CAD_dispatch'])

    def test_exception_after_dispatch_preserves_uncertainty(self):
        def crash(n, a): raise TimeoutError('fixture')
        self.engine.dispatch = crash
        with self.assertRaises(TimeoutError): self.engine.run('one', self.steps)
        self.assertEqual(self.engine.status('one')['status'], 'UNCERTAIN')
        self.assertEqual(self.engine.gate.snapshot()['status'], 'FROZEN')

    def test_plan_holds_mutex_between_steps(self):
        observations = []
        original = self.engine.dispatch
        def dispatch(n, a):
            observations.append(self.engine.gate.snapshot()['status'])
            other = PlanEngine(self.root / 'other', self.root / 'gate.sqlite', lambda n, a: 'unexpected')
            self.assertEqual(other.run('competing-' + n, [{'id': n, 'tool': n}])['status'], 'REJECTED_BUSY')
            return original(n, a)
        self.engine.dispatch = dispatch
        self.engine.run('one', self.steps)
        self.assertEqual(observations, ['RUNNING'] * 3)

    def test_progress_visible_during_blocked_dispatch_and_restart_cache(self):
        entered, release = threading.Event(), threading.Event()
        def dispatch(n, a): entered.set(); release.wait(5); return 'returned'
        self.engine.dispatch = dispatch
        worker = threading.Thread(target=lambda: self.engine.run('one', self.steps[:1])); worker.start()
        self.assertTrue(entered.wait(3))
        other = PlanEngine(self.root, self.root / 'gate.sqlite', dispatch)
        status = other.status('one')
        self.assertEqual(status['status'], 'RUNNING')
        self.assertEqual(status['events'][-1]['type'], 'step_started')
        self.assertTrue(other.run('one', self.steps[:1])['cached_no_CAD_dispatch'])
        release.set(); worker.join(5); self.assertFalse(worker.is_alive())

    def test_no_checks_is_not_verified(self):
        result = self.engine.run('one', self.steps[:1])
        self.assertFalse(result['declared_checks_passed'])
        self.assertEqual(result['results'][0]['verification']['status'], 'NOT_REQUESTED')

    def test_nested_plan_or_duplicate_step_rejected(self):
        with self.assertRaises(ValueError): self.engine.run('one', [{'id': 'x', 'tool': 'catia_plan_run'}])
        with self.assertRaises(ValueError): self.engine.run('two', self.steps[:1]*2)

    def test_structured_failure_is_preserved(self):
        value = normalize('test', {'structuredContent': {'ok': False, 'code': 'BAD_GEOMETRY', 'effects': {'modified': True}}, 'isError': True})
        self.assertFalse(value['ok']); self.assertTrue(value['effects']['modified'])
        self.assertEqual(value['completion'], 'KNOWN_FINISHED')


if __name__ == '__main__': unittest.main()
