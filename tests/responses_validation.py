"""Offline protocol validation only; does not claim a real GPT/CATIA result."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Agent
from cc_switch import load_micu
from providers import MICU_BASE, MICU_MODEL, PROVIDERS, NoRedirect, endpoint
from responses_api import request_responses


class Controller:
    cancel = threading.Event()
    def __init__(self, workspace):
        self.workspace = workspace
        self.reads = 0
        self.writes = 0
    def info(self):
        self.reads += 1
        return {'document': 'test-only.CATPart'}
    def __getattr__(self, name):
        def write(**kwargs):
            self.writes += 1
            return {}
        return write


class SSE(BytesIO):
    headers = {'Content-Type': 'text/event-stream'}
    def __init__(self, events):
        super().__init__(''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode())


def completed(output):
    return {'type': 'response.completed', 'response': {'id': 'resp-test', 'model': MICU_MODEL, 'status': 'completed', 'output': output}}


class Tests(unittest.TestCase):
    def test_endpoint_and_redirect(self):
        self.assertEqual(endpoint(MICU_BASE, MICU_MODEL, PROVIDERS[3]), MICU_BASE+'/responses')
        self.assertEqual(endpoint(MICU_BASE+'/responses', MICU_MODEL, PROVIDERS[3]), MICU_BASE+'/responses')
        for url in ('http://www.micuapi.ai/v1', 'https://other.example/v1', 'https://www.micuapi.ai/v1?key=test', 'https://www.micuapi.ai/v1/chat/completions'):
            with self.assertRaises(ValueError):
                endpoint(url, MICU_MODEL, PROVIDERS[3])
        with self.assertRaises(RuntimeError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')

    def test_tool_loop_replay_and_approval(self):
        requests, approved, emitted = [], [], []
        reasoning = {'type': 'reasoning', 'id': 'rs-test', 'summary': [], 'encrypted_content': 'test-ciphertext'}
        output = [reasoning,
                  {'type': 'function_call', 'call_id': 'read1', 'name': 'inspect_catia', 'arguments': '{}'},
                  {'type': 'function_call', 'call_id': 'write1', 'name': 'write_notebook', 'arguments': '{"name":"denied.py","source":"test"}'}]
        text = {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '已读取；写入被拒绝。'}]}
        def transport(request, provider):
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, MICU_BASE+'/responses')
            self.assertEqual(request.get_header('User-agent'), 'PhyXiCATIAAgent/0.5.2')
            self.assertEqual(payload['model'], MICU_MODEL)
            self.assertFalse(payload['store'])
            self.assertTrue(payload['stream'])
            self.assertIn('name', payload['tools'][0])
            self.assertNotIn('function', payload['tools'][0])
            requests.append(payload)
            if len(requests) == 1:
                return SSE([completed(output)])
            self.assertIn(reasoning, payload['input'])
            results = [json.loads(item['output']) for item in payload['input'] if item.get('type') == 'function_call_output']
            self.assertTrue(results[0]['ok'])
            self.assertFalse(results[1]['ok'])
            return SSE([{'type': 'response.output_text.delta', 'delta': '已读取；写入被拒绝。'}, completed([text])])
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(Path(folder))
            agent = Agent(controller, emitted.append, lambda name, args: approved.append(name) or False, lambda: '')
            with patch('responses_api.open_request', transport):
                agent.send('test', MICU_BASE, 'test-key', MICU_MODEL, {}, PROVIDERS[3])
            self.assertEqual(len(requests), 2)
            self.assertEqual(controller.reads, 1)
            self.assertEqual(controller.writes, 0)
            self.assertEqual(approved, ['write_notebook'])
            self.assertEqual(''.join(emitted).count('已读取；写入被拒绝。'), 1)

    def test_incomplete_stream_never_returns_tool_call(self):
        controller = Controller(Path('.'))
        with patch('responses_api.open_request', lambda *args: SSE([{'type': 'response.output_item.done', 'item': {'type': 'function_call', 'name': 'write_notebook'}}])):
            with self.assertRaises(RuntimeError):
                request_responses(MICU_BASE, 'test-key', MICU_MODEL, [], [], PROVIDERS[3], controller, lambda _: None)
        self.assertEqual(controller.writes, 0)

    def test_cc_switch_import_is_readonly_and_restricted(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'cc-switch.db'
            c = sqlite3.connect(db)
            c.execute('CREATE TABLE providers(app_type TEXT,is_current INTEGER,settings_config TEXT)')
            config = 'model="gpt-6.1-sol"\nmodel_provider="custom"\n[model_providers.custom]\nbase_url="https://www.micuapi.ai/v1"\nwire_api="responses"'
            data = {'auth': {'OPENAI_API_KEY': 'test-only-key'}, 'config': config}
            c.execute('INSERT INTO providers VALUES(?,?,?)', ('codex', 1, json.dumps(data)))
            c.commit()
            before = db.read_bytes()
            self.assertEqual(load_micu(db)['key'], 'test-only-key')
            self.assertEqual(db.read_bytes(), before)
            data['config'] = config.replace('www.micuapi.ai', 'other.example')
            c.execute('UPDATE providers SET settings_config=?', (json.dumps(data),))
            c.commit()
            with self.assertRaises(ValueError):
                load_micu(db)
            c.close()


if __name__ == '__main__':
    unittest.main()
