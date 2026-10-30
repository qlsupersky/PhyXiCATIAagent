"""A returned script failure must permit a corrected new request, without replay."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from native_contract import screen_macro, sha
from native_runtime import OpenCodeRuntime
from native_service import NativeService
from test_native_core import fixture, MACRO


class ScriptFailure(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['PHYXI_TEST_WORK'])
        self.root = Path(self.temp.name)
        self.service, self.job = fixture(self.root)
        self.service.reserve(self.job)
        self.claim = self.service.claim(self.job, MACRO)
        self.manifest = self.claim['manifest']
        bound = {'run_id': self.job, 'macro_sha256': self.manifest['macro_sha256'], 'checks_sha256': self.manifest['checks_sha256']}
        self.rows = [
            {'name': 'com_return_observed', 'detail': {'returned_error': True}},
            {'name': 'macro_runtime_failed', 'detail': {**bound, 'known_script_engine_return': True, 'message': 'Microsoft VBScript runtime error'}},
            {'name': 'probe_error', 'detail': {'type': 'COMException'}},
            {'name': 'execution_finished', 'detail': {**bound, 'com_return_observed': True, 'script_error_returned': True, 'outcome': 'FAILED'}}]
        self.exit = {'child_return_observed': True, 'returncode': 2}

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_script_error_releases_and_caches_failure(self):
        result = self.service.terminal_failure(self.job, self.claim['owner'], self.manifest, self.rows, self.exit)
        self.assertEqual(result['reason'], 'macro_runtime_error')
        self.assertEqual(result['completion'], 'KNOWN_FINISHED')
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')
        with patch('native_service.subprocess.run', side_effect=AssertionError('never replay')):
            self.assertTrue(self.service.run(self.job, MACRO)['cached_no_CAD_dispatch'])

    def test_script_error_restart_reconciles_from_bound_exit(self):
        folder = self.service.folder(self.job)
        log = folder / 'execute.stdout.jsonl'
        log.write_text('\n'.join(json.dumps(r) for r in self.rows) + '\n', encoding='utf-8')
        record = {**self.exit, 'bridge_sha256': self.manifest['bridge_sha256'], 'stdout_sha256': sha(log.read_bytes())}
        (folder / 'bridge-exit.json').write_text(json.dumps(record), encoding='utf-8')
        self.service.finish(self.job, self.claim['owner'])
        recovered = NativeService(self.root, self.root / 'gate.sqlite')
        self.assertEqual(recovered.snapshot()['status'], 'IDLE')
        self.assertEqual(json.loads(recovered.job(self.job)['result_json'])['reason'], 'macro_runtime_error')

    def test_rpc_unknown_and_mismatched_script_evidence_stay_blocked(self):
        for kind in ['com', 'binding', 'flag', 'tail']:
            rows = json.loads(json.dumps(self.rows))
            if kind == 'com': rows[-1]['detail']['com_return_observed'] = False
            if kind == 'binding': rows[1]['detail']['macro_sha256'] = 'wrong'
            if kind == 'flag': rows[-1]['detail']['script_error_returned'] = False
            if kind == 'tail': rows.append({'name': 'untrusted_tail'})
            self.assertIsNone(self.service.terminal_failure_result(self.job, self.manifest, rows, self.exit))
        self.assertEqual(self.service.snapshot()['status'], 'RUNNING')

    def test_partnumber_error_is_detected_before_cad(self):
        with self.assertRaisesRegex(ValueError, 'doc.Product.PartNumber'):
            screen_macro(MACRO.replace('End Sub', 'part.PartNumber="Bad"\nEnd Sub'))
        self.assertIsInstance(screen_macro(MACRO.replace('End Sub', 'doc.Product.PartNumber="Good"\nEnd Sub')), bytes)

    def test_historical_failed_macro_remains_cached_after_new_screening(self):
        bad = MACRO.replace('End Sub', 'part.PartNumber="OldBad"\nEnd Sub')
        # Model a legitimately consumed pre-upgrade job; do not execute it.
        with self.service._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (self.job,)).fetchone()
            manifest = json.loads(row['manifest_json'])
            manifest['macro_sha256'] = sha(bad.encode())
            db.execute("UPDATE native_ui_jobs SET manifest_json=?,state='FAILED',result_json=? WHERE job_id=?",
                       (json.dumps(manifest), json.dumps({'state': 'FAILED', 'passed': False}), self.job))
        with patch('native_service.subprocess.run', side_effect=AssertionError('never replay')):
            cached = self.service.run(self.job, bad)
        self.assertEqual(cached['state'], 'FAILED')
        self.assertTrue(cached['cached_no_CAD_dispatch'])

    def test_isolated_engine_inherits_only_second_mcp_and_shared_gate(self):
        runtime = OpenCodeRuntime(self.root, self.root / 'shared.sqlite')
        interpreter, launcher = self.root / 'python.exe', self.root / 'launch.py'
        interpreter.touch(); launcher.touch()
        config = self.root / 'global.json'
        config.write_text(json.dumps({'providers': {'never-copy': {'secret': 'fixture'}}, 'mcp': {'catia-v5': {
            'type': 'local', 'command': [str(interpreter), str(launcher)], 'environment': {'PHYXI_NATIVE_GATE': 'wrong'}}}}), encoding='utf-8')
        entries = runtime.mcp_configuration(interpreter, config)
        self.assertEqual(set(entries), {'native-modeling', 'catia-v5'})
        self.assertEqual(entries['catia-v5']['environment']['PHYXI_NATIVE_GATE'], str(runtime.gate))
        self.assertNotIn('never-copy', json.dumps(entries))

    def test_isolated_health_connects_loaded_but_unstarted_servers(self):
        runtime = OpenCodeRuntime(self.root, self.root / 'shared.sqlite')
        connected = []
        def api(method, path, body=None, **kwargs):
            if method == 'PUT':
                connected.append(path.rsplit('/', 1)[1])
                return None
            return {'data': [{'name': name, 'status': {'status': 'connected'}} for name in connected]}
        config = [{'info': {'model': {'providerID': 'phyxi-deepseek', 'model': 'deepseek-flash'},
                             'mcp': {'servers': {'native-modeling': {'type': 'local'}, 'catia-v5': {'type': 'local'}}}}}]
        with patch.object(runtime, 'api', side_effect=api):
            status = runtime._health(config)
        self.assertEqual(set(connected), {'native-modeling', 'catia-v5'})
        self.assertTrue(status['connected'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
