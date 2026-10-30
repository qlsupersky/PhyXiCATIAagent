"""Official provider isolation, credentials, and streamed native tool integrity."""
import json
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers import PROVIDERS, DEEPSEEK_BASE, DEEPSEEK_MODEL, endpoint, NoRedirect
from agent import Agent
from deepseek_connection import load_deepseek


class Response(BytesIO):
    headers = {'Content-Type': 'text/event-stream'}


def stream(chunks):
    return Response(('\n'.join('data: '+json.dumps(c) for c in chunks)+'\ndata: [DONE]\n').encode())


class Tests(unittest.TestCase):
    def test_official_urls_and_model_isolation(self):
        for base in (DEEPSEEK_BASE, DEEPSEEK_BASE+'/', DEEPSEEK_BASE+'/v1', DEEPSEEK_BASE+'/chat/completions'):
            self.assertTrue(endpoint(base, DEEPSEEK_MODEL, PROVIDERS[5]).endswith('/chat/completions'))
        for base in ('http://api.deepseek.com', 'https://api.deepseek.com.evil.test',
                     'https://api.deepseek.com:444', DEEPSEEK_BASE+'?api_key=x',
                     'https://user:password@api.deepseek.com', DEEPSEEK_BASE+'/other'):
            with self.subTest(base=base), self.assertRaises(ValueError):
                endpoint(base, DEEPSEEK_MODEL, PROVIDERS[5])
        for provider in PROVIDERS[:5]:
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                endpoint(DEEPSEEK_BASE, DEEPSEEK_MODEL, provider)
        with self.assertRaises(ValueError):
            endpoint(DEEPSEEK_BASE, 'qwen3.8-base', PROVIDERS[5])

    def test_redirect_refused(self):
        with self.assertRaises(RuntimeError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def agent(self):
        controller = type('Controller', (), {'cancel': threading.Event()})()
        agent = Agent(controller, lambda _: None, lambda *_: False, lambda: '')
        agent.provider = PROVIDERS[5]
        return agent

    def test_native_tool_fragments_and_exact_model(self):
        def transport(req, provider):
            data = json.loads(req.data)
            self.assertEqual(data['model'], DEEPSEEK_MODEL)
            self.assertEqual(data['thinking'], {'type': 'disabled'})
            self.assertEqual(data['temperature'], 1.0)
            self.assertEqual(provider, PROVIDERS[5])
            self.assertIn('tools', data)
            return stream([
                {'model':DEEPSEEK_MODEL,'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call1','function':{'name':'inspect_','arguments':'{'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'catia','arguments':'}'}}]},'finish_reason':'tool_calls'}]},
            ])
        agent = self.agent()
        with patch('agent.open_request', transport):
            reply = agent.request(DEEPSEEK_BASE, 'test-only', DEEPSEEK_MODEL, [])
        call = reply['tool_calls'][0]
        self.assertEqual(call['function'], {'name':'inspect_catia','arguments':'{}'})
        self.assertEqual(agent.last_response_metadata['model'], DEEPSEEK_MODEL)

    def test_no_key_no_network(self):
        with patch('agent.open_request') as transport, self.assertRaises(ValueError):
            self.agent().request(DEEPSEEK_BASE, '', DEEPSEEK_MODEL, [])
        transport.assert_not_called()

    def test_truncated_tool_never_returned(self):
        response = stream([{'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'build_surface','arguments':'{}'}}]},'finish_reason':'length'}]}])
        with patch('agent.open_request', return_value=response), self.assertRaises(ValueError):
            self.agent().request(DEEPSEEK_BASE, 'test-only', DEEPSEEK_MODEL, [])

    def test_missing_credential_never_uses_qwen(self):
        with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as folder:
            path=Path(folder)
            with patch('deepseek_connection.Path.home',return_value=path), self.assertRaises(ValueError):
                load_deepseek(path/'config.json')


if __name__ == '__main__':
    unittest.main()
