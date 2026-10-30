"""Offline tests: approval, tampering, concurrency and crash safety. No COM."""
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_contract import sha, screen_macro, validate_checks
from native_service import NativeService
from native_workflow import proposal_hash
from native_gate import GateBlocked

MACRO = 'Language="VBSCRIPT"\nSub CATMain(runId, outputPath, resultPath)\nDim doc,part,body\nSet doc=CATIA.Documents.Add("Part")\nSet part=doc.Part\nSet body=part.MainBody\nbody.Name="Own_" & runId\nEnd Sub\n'
CHECKS = {'features': [{'name': 'BasePad', 'depth_mm': 12}], 'sketch_count': 1, 'volume_mm3': 72000}


def fixture(root):
    service = NativeService(root, root / 'gate.sqlite')
    job = 'native-' + 'a' * 24
    folder = service.jobs / job; folder.mkdir()
    (folder / 'REVIEWED.CATScript').write_bytes(MACRO.encode())
    (folder / 'CHECKS.json').write_bytes(json.dumps(CHECKS).encode())
    (folder / 'NativeModeling.exe').write_bytes(b'not executable; offline fixture only')
    manifest = {'job_id': job, 'requirement': 'offline only', 'approval_origin': 'local_ui_full_source_review',
                'macro_sha256': sha(MACRO.encode()), 'checks_sha256': sha((folder / 'CHECKS.json').read_bytes()),
                'bridge_sha256': sha((folder / 'NativeModeling.exe').read_bytes())}
    service.register(manifest)
    return service, job


def contender(root, start, results):
    service = NativeService(Path(root), Path(root) / 'gate.sqlite'); start.wait()
    try:
        service.claim('native-' + 'a' * 24, MACRO); results.put('won')
    except GateBlocked:
        results.put('blocked')


def crash(root):
    service = NativeService(Path(root), Path(root) / 'gate.sqlite')
    service.claim('native-' + 'a' * 24, MACRO); os._exit(17)


class NativeCore(unittest.TestCase):
    def setUp(self):
        evidence = Path(os.environ['PHYXI_TEST_WORK']); evidence.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=evidence)
        self.root = Path(self.temp.name); self.service, self.job = fixture(self.root)

    def tearDown(self): self.temp.cleanup()

    def test_unapproved_and_modified_no_dispatch(self):
        for job, code in [('unknown', MACRO), (self.job, MACRO + '\n')]:
            with self.assertRaises(ValueError): self.service.claim(job, code)
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')

    def test_checks_and_bridge_tamper(self):
        folder = self.service.folder(self.job)
        for name in ['CHECKS.json', 'NativeModeling.exe', 'REVIEWED.CATScript']:
            path = folder / name; original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.assertRaises(ValueError): self.service.claim(self.job, MACRO)
            path.write_bytes(original)
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')

    def test_once_and_cache(self):
        self.service.reserve(self.job)
        claimed = self.service.claim(self.job, MACRO)
        with self.assertRaises(GateBlocked): self.service.claim(self.job, MACRO)
        self.service.finish(self.job, claimed['owner'], {'offline_fixture': True})
        with patch('native_service.subprocess.run', side_effect=AssertionError('must not dispatch')):
            self.assertTrue(self.service.run(self.job, MACRO)['cached_no_CAD_dispatch'])

    def test_freeze_no_expiry(self):
        self.service.reserve(self.job)
        claimed = self.service.claim(self.job, MACRO); self.service.finish(self.job, claimed['owner'])
        with self.assertRaises(GateBlocked): NativeService(self.root, self.root / 'gate.sqlite').claim(self.job, MACRO)
        self.assertEqual(self.service.snapshot()['status'], 'FROZEN')

    def test_shared_gate_other_services(self):
        from native_gate import SessionGate
        other = SessionGate(self.root / 'gate.sqlite'); token = other.acquire('other-service')
        with self.assertRaises(GateBlocked): self.service.claim(self.job, MACRO)
        other.complete(token, {'fixture': True})
        self.service.reserve(self.job)
        self.service.claim(self.job, MACRO)

    def test_real_process_race(self):
        self.service.reserve(self.job)
        ctx = multiprocessing.get_context('spawn'); start = ctx.Event(); results = ctx.Queue()
        processes = [ctx.Process(target=contender, args=(str(self.root), start, results)) for _ in range(2)]
        for p in processes: p.start()
        start.set(); actual = [results.get(timeout=20) for _ in processes]
        for p in processes: p.join(10); self.assertEqual(p.exitcode, 0)
        results.close(); results.join_thread(); self.assertCountEqual(actual, ['won', 'blocked'])

    def test_process_crash_no_replay(self):
        self.service.reserve(self.job)
        ctx = multiprocessing.get_context('spawn'); p = ctx.Process(target=crash, args=(str(self.root),)); p.start(); p.join(20)
        self.assertEqual(p.exitcode, 17)
        with self.assertRaises(GateBlocked): self.service.claim(self.job, MACRO)
        self.assertEqual(self.service.snapshot()['status'], 'RUNNING')

    def test_checks_reject_nan_injection_and_duplicates(self):
        for update in [{'volume_mm3': float('nan')}, {'volume_mm3': -1}, {'sketch_count': True},
                       {'features': [{'name': 'A"; evil'}]}, {'features': [{'name': 'A'}, {'name': 'A'}]}]:
            with self.assertRaises(ValueError): validate_checks({**CHECKS, **update})
        self.assertIsNone(validate_checks({**CHECKS, 'volume_mm3': None})['volume_mm3'])

    def test_macro_screen_not_approval(self):
        for code in [MACRO + '\nCreateObject("WScript.Shell")', MACRO.replace('Part")', 'Part")\nCATIA.Quit'),
                     MACRO.replace('End Sub', 'x=20#\nEnd Sub'), MACRO.replace('Own_', 'Other_'),
                     MACRO.replace('Sub CATMain', 'Option Explicit\nSub CATMain')]:
            with self.assertRaises(ValueError): screen_macro(code)
        self.assertEqual(screen_macro(MACRO), MACRO.encode())
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')

    def test_review_hash_binds_checks_and_source(self):
        proposal = {'summary': 'fixture', 'macro_ascii': MACRO, 'checks': CHECKS}
        expected = proposal_hash(proposal)
        for field in ['checks', 'macro_ascii', 'summary']:
            changed = copy.deepcopy(proposal)
            if field == 'checks': changed['checks']['volume_mm3'] = 5
            else: changed[field] += '\n'
            with self.assertRaises(ValueError): self.service.prepare('fixture', changed, expected)

    def test_compile_bound_bridge_no_COM(self):
        proposal = {'summary': 'compile only', 'macro_ascii': MACRO, 'checks': CHECKS}
        manifest = self.service.prepare('fixture; no execution', proposal, proposal_hash(proposal))
        self.assertTrue((self.service.folder(manifest['job_id']) / 'NativeModeling.exe').is_file())
        self.assertEqual(self.service.job(manifest['job_id'])['state'], 'APPROVED')
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')

    def test_actual_opencode_tool_metadata_location(self):
        from native_runtime import tool_calls
        call = {'tool': 'native-modeling.modeling_run', 'status': 'completed', 'input': {'job_id': self.job, 'macro_ascii': MACRO}}
        rows = [{'type': 'assistant', 'content': [{'type': 'tool', 'name': 'execute', 'state': {'status': 'completed', 'metadata': {'toolCalls': [call]}}}]}]
        self.assertEqual(tool_calls(rows), [call])

    def test_approved_not_yet_reserved_cannot_dispatch(self):
        with self.assertRaises(GateBlocked): self.service.claim(self.job, MACRO)
        self.service.reserve(self.job)
        self.assertEqual(self.service.snapshot()['operation'], 'native_pending:' + self.job)
        from native_gate import SessionGate
        with self.assertRaises(GateBlocked): SessionGate(self.root/'gate.sqlite').acquire('legacy')
        with self.assertRaises(GateBlocked): self.service.reserve(self.job)

    def test_prompt_timeout_blocks_other_CAD_no_replay(self):
        from native_workflow import NativeWorkflow
        workflow = NativeWorkflow(self.root, self.root/'gate.sqlite')
        discovery = {'session': 'fixture', 'folder': str(self.root), 'messages': [{'type': 'assistant', 'content': [
            {'type': 'tool', 'name': 'execute', 'state': {'status': 'completed',
             'metadata': {'toolCalls': [{'tool': 'search'}]}, 'content': [{'type': 'text', 'text': json.dumps({'items': [{'path': 'tools["native-modeling"].modeling_run'}]})}]}}]}]}
        manifest = json.loads(self.service.job(self.job)['manifest_json'])
        with patch.object(workflow.runtime, 'connect'), patch.object(workflow.runtime, 'prompt', side_effect=[discovery, TimeoutError('fixture')]) as prompt:
            with self.assertRaises(TimeoutError): workflow.execute(manifest)
            self.assertEqual(prompt.call_count, 2)
            with self.assertRaises(RuntimeError): workflow.execute(manifest)
            self.assertEqual(prompt.call_count, 2)
        self.assertEqual(self.service.snapshot()['operation'], 'native_pending:' + self.job)
        self.assertEqual(self.service.job(self.job)['state'], 'APPROVED')

    def test_terminal_no_tool_settles_without_replay(self):
        from native_workflow import NativeWorkflow
        workflow = NativeWorkflow(self.root, self.root/'gate.sqlite')
        self.service.reserve(self.job)
        workflow.audit_calls(self.job, [{'type': 'idle', 'outcome': 'succeeded'}], 'fixture', str(self.root))
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')
        self.assertEqual(self.service.job(self.job)['state'], 'FROZEN')
        with self.assertRaises(GateBlocked): self.service.claim(self.job, MACRO)

    def test_legacy_bridge_shares_gate_and_error_freezes(self):
        from controller import Controller
        # Release source has no local config; use this fixture's workspace gate.
        controller = Controller(self.root)
        self.assertNotEqual(controller.native_gate.path, self.service.path)
        controller.native_gate = self.service
        self.service.reserve(self.job)
        with patch.object(controller, 'process') as process:
            with self.assertRaises(GateBlocked): controller.info()
            process.assert_not_called()
        self.service.settle_without_dispatch(self.job, {'fixture': 'terminal with no CAD call'})
        with patch.object(controller, 'process', return_value=(0, '{"ok":true,"result":{"fixture":true}}', '')):
            self.assertTrue(controller.info()['fixture'])
        self.assertEqual(self.service.snapshot()['status'], 'IDLE')
        with patch.object(controller, 'process', side_effect=TimeoutError('fixture no COM')):
            with self.assertRaises(TimeoutError): controller.info()
        self.assertEqual(self.service.snapshot()['status'], 'FROZEN')

    def test_factory_alias_misuse_rejected(self):
        bad = MACRO.replace('End Sub', 'Set sk=body.Sketches.Add(part.OriginElements.PlaneXY)\nSet f=sk\nf.CreateClosedCircle 0,0,10\nEnd Sub')
        with self.assertRaises(ValueError): screen_macro(bad)


if __name__ == '__main__': unittest.main(verbosity=2)
