"""Shared-service regressions: files, tools, continuity and uncertain submission."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opencode_link import OpenCodeLink, Rejected, render_messages


class FakeLink(OpenCodeLink):
    def __init__(self, root):
        super().__init__(root / 'workspace', root / 'project')
        self.session = 'ses_fixture'
        self.url = 'http://127.0.0.1:1234'
        self.rows = [{'id': 'idle_old', 'type': 'idle', 'outcome': 'succeeded'}]
        self.calls = []
        self.failure = None
        self.finish = True

    def api(self, method, path, body=None, timeout=20, **kwargs):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == 'GET' and '/message?' in path:
            return {'data': self.rows}
        if path.endswith('/prompt'):
            if isinstance(self.failure, Rejected):
                raise self.failure
            files = [{'name': f['name'], 'mime': f['uri'].split(':', 1)[1].split(';')[0],
                      'data': f['uri'].split(',', 1)[1]} for f in body.get('files', [])]
            self.rows.insert(0, {'id': body['id'], 'type': 'user', 'text': body['text'], 'files': files})
            if self.finish: self.settle()
            if self.failure: raise self.failure
            return None
        if path.endswith('/model'):
            self.rows.insert(0, {'id': 'switch', 'type': 'model-switched'})
        return {'data': {}}

    def settle(self):
        self.rows.insert(0, {'id': 'a_' + str(len(self.rows)), 'type': 'assistant', 'content': [
            {'type': 'text', 'text': '图中三个圆'}, {'type': 'tool', 'name': 'write', 'state':
                {'status': 'completed', 'output': 'file saved'}}]})
        self.rows.insert(0, {'id': 'i_' + str(len(self.rows)), 'type': 'idle', 'outcome': 'succeeded'})


class SharedLinkTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ['PHYXI_TEST_WORK']); root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)
        self.link = FakeLink(self.root)

    def tearDown(self): self.temp.cleanup()

    def posts(self):
        return [c for c in self.link.calls if c[0] == 'POST' and c[1].endswith('/prompt')]

    def test_file_bytes_verified_and_tools_retained_in_same_session(self):
        data = b'actual-file-bytes'
        result = self.link.send('未追加系统约束', [{'name': 'note.txt', 'data': data, 'mime': 'text/plain'}])
        self.assertEqual(result['attachments_verified'][0]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertIn('工具：write [completed]', result['text'])
        self.assertIn('file saved', result['text'])
        self.link.send('继续上一轮')
        self.assertEqual(len(self.posts()), 2)
        self.assertTrue(all('/ses_fixture/prompt' in c[1] for c in self.posts()))
        self.assertEqual(set(self.posts()[0][2]), {'id', 'text', 'files'})
        self.assertEqual(self.posts()[0][2]['text'], '未追加系统约束')

    def test_post_timeout_observes_completion_without_retry(self):
        self.link.failure = TimeoutError('timeout')
        self.assertEqual(self.link.send('one')['outcome'], 'succeeded')
        self.assertEqual(len(self.posts()), 1)

    def test_cancel_unknown_keeps_pending_across_restart_and_refresh_settles(self):
        self.link.failure = TimeoutError('timeout'); self.link.finish = False
        cancel = threading.Event(); cancel.set()
        with self.assertRaisesRegex(RuntimeError, '停止等待'):
            self.link.send('must not replay', cancel=cancel)
        pending = self.link._pending()
        self.assertTrue(pending.exists())
        with self.assertRaisesRegex(RuntimeError, '不要重发'):
            self.link.send('duplicate')
        with self.assertRaisesRegex(RuntimeError, '不要重发'):
            self.link.switch({'id': 'other', 'providerID': 'example'})
        self.assertEqual(len(self.posts()), 1)
        self.link.settle()
        restored = FakeLink(self.root); restored.rows = self.link.rows
        result = restored.refresh()
        self.assertFalse(result['pending'])
        self.assertEqual(result['completed']['outcome'], 'succeeded')
        self.assertEqual(restored.calls[0][0], 'GET')

    def test_definitive_http_rejection_is_not_retried(self):
        self.link.failure = Rejected(413)
        with self.assertRaises(Rejected): self.link.send('too large')
        self.assertFalse(self.link._pending().exists())
        self.assertEqual(len(self.posts()), 1)

    def test_5xx_without_completion_remains_pending(self):
        self.link.failure = Rejected(500)
        cancel = threading.Event(); cancel.set()
        with self.assertRaisesRegex(RuntimeError, '停止等待'): self.link.send('uncertain', cancel=cancel)
        self.assertTrue(self.link._pending().exists())
        self.assertEqual(len(self.posts()), 1)

    def test_attachment_substitution_does_not_claim_verified(self):
        self.link.finish = False
        def tamper(text): self.link.rows[0]['files'][0]['data'] = base64.b64encode(b'wrong').decode()
        with self.assertRaisesRegex(RuntimeError, '字节不符'):
            self.link.send('read', [{'name': 'x', 'mime': 'text/plain', 'data': b'correct'}], progress=tamper)
        self.assertTrue(self.link._pending().exists())

    def test_model_switch_metadata_does_not_look_like_running_turn(self):
        self.link.switch({'id': 'chosen', 'providerID': 'provider', 'variant': 'high'})
        self.assertEqual(self.link.send('after switching')['outcome'], 'succeeded')
        body = next(c[2] for c in self.link.calls if c[1].endswith('/model'))
        self.assertEqual(body['model']['variant'], 'high')

    def test_running_session_rejects_new_send_without_dispatch(self):
        self.link.rows.insert(0, {'id': 'u_active', 'type': 'user'})
        with self.assertRaisesRegex(RuntimeError, '仍在运行'): self.link.send('second')
        self.assertFalse(self.posts())

    def test_long_tool_turn_pages_to_find_exact_user(self):
        first = [{'id': 'idle_new', 'type': 'idle'}]
        second = [{'id': 'user_target', 'type': 'user'}]
        with patch.object(self.link, 'api', side_effect=[{'data': first, 'cursor': {'next': 'opaque'}}, {'data': second}]) as api:
            self.assertEqual(len(self.link.messages('user_target')), 2)
            self.assertIn('cursor=opaque', api.call_args_list[1].args[1])
            self.assertNotIn('order=', api.call_args_list[1].args[1])

    def test_full_interface_uses_same_session_project_and_no_password(self):
        with patch('opencode_link.cli_path', return_value=Path('opencode.exe')), patch('opencode_link.subprocess.Popen') as popen:
            self.link.open_full_interface()
            args = popen.call_args.args[0]
            self.assertEqual(args, ['opencode.exe', str(self.link.project), '--auto', '--session', 'ses_fixture'])
            self.assertEqual(popen.call_args.kwargs['cwd'], self.link.project)

    def test_interrupt_only_sends_backend_interrupt(self):
        self.link.interrupt()
        self.assertTrue(self.link.calls[0][1].endswith('/interrupt?resume=false'))
        self.assertFalse(self.posts())

    def test_saved_session_restores_only_in_its_project(self):
        self.link._save_current()
        restored = OpenCodeLink(self.link.workspace, self.link.project)
        other = OpenCodeLink(self.link.workspace, self.root / 'other')
        self.assertEqual(restored.session, 'ses_fixture')
        self.assertIsNone(other.session)


if __name__ == '__main__': unittest.main()
