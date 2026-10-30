"""No-approval routes plus deduplication and integrity regressions. No COM."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_workflow import NativeWorkflow, proposal_hash
from native_service import NativeService
from native_gate import GateBlocked
from test_native_core import MACRO, CHECKS


class AutomaticExecution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['PHYXI_TEST_WORK'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_direct_request_needs_no_local_review_and_deduplicates(self):
        service = NativeService(self.root)
        calls = []
        def run(job, code):
            claimed = service.claim(job, code)
            if 'cached' in claimed:
                return {**claimed['cached'], 'cached_no_CAD_dispatch': True}
            calls.append(job)
            service.finish(job, claimed['owner'], {'fixture_success': True})
            return {'fixture_success': True}
        with patch.object(service, 'run', side_effect=run):
            result = service.execute_request('same-user-operation', 'fixture', MACRO, CHECKS)
            self.assertTrue(result['fixture_success'])
            repeated = service.execute_request('same-user-operation', 'fixture', MACRO, CHECKS)
            self.assertTrue(repeated['cached_no_CAD_dispatch'])
            with self.assertRaises(ValueError):
                service.execute_request('same-user-operation', 'changed request', MACRO, CHECKS)
        self.assertEqual(len(calls), 1)
        manifest = json.loads(service.job(calls[0])['manifest_json'])
        self.assertFalse(manifest['interactive_approval_required'])
        self.assertEqual(manifest['approval_origin'], 'user_authorized_automatic_execution')
        self.assertEqual(service.snapshot()['status'], 'IDLE')

    def test_unknown_execution_is_never_auto_unlocked(self):
        service = NativeService(self.root)
        with patch.object(service, 'run', side_effect=TimeoutError('fixture, no CAD')):
            with self.assertRaises(TimeoutError):
                service.execute_request('unknown', 'fixture', MACRO, CHECKS)
        with patch.object(service, 'run') as run:
            with self.assertRaises(GateBlocked):
                service.execute_request('unknown', 'fixture', MACRO, CHECKS)
            run.assert_not_called()
        self.assertEqual(service.snapshot()['status'], 'RUNNING')

    def test_single_workflow_request_generates_prepares_and_executes(self):
        workflow = NativeWorkflow(self.root)
        folder = workflow.fresh('proposal'); folder.mkdir()
        proposal = {'summary': 'fixture', 'macro_ascii': MACRO, 'checks': CHECKS}
        record = {'requirement': 'fixture', 'proposal': proposal, 'proposal_sha256': proposal_hash(proposal),
                  'source_session': 'fixture', 'folder': str(folder)}
        callback = Mock()
        with patch.object(workflow, 'generate', return_value=record), \
             patch.object(workflow, 'execute', return_value={'state': 'SUCCEEDED'}) as execute:
            self.assertEqual(workflow.generate_and_execute('fixture', on_prepared=callback)['state'], 'SUCCEEDED')
        callback.assert_called_once()
        execute.assert_called_once()
        manifest = execute.call_args.args[0]
        self.assertFalse(manifest['interactive_approval_required'])

    def test_legacy_ui_callbacks_do_not_create_modal_or_wait(self):
        from app import Panel
        panel = SimpleNamespace(controller=SimpleNamespace(cancel=SimpleNamespace(is_set=lambda: False)))
        callback = Mock()
        with patch('app.tk.Toplevel', side_effect=AssertionError('no review dialog')):
            self.assertTrue(Panel.approve(panel, 'fixture', {}))
            Panel.approval_dialog(panel, 'fixture', {}, callback)
        callback.assert_called_once_with(True)

    def test_legacy_agent_does_not_call_approval_callback(self):
        from agent import Agent
        controller = Mock()
        controller.cancel.is_set.return_value = False
        controller.write_notebook.return_value = {'written': 'fixture'}
        approval = Mock(side_effect=AssertionError('must not request approval'))
        agent = Agent(controller, lambda text: None, approval, lambda: '')
        result = agent.execute('write_notebook', {'name': 'fixture', 'source': 'fixture'})
        self.assertTrue(result['ok'])
        approval.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
