"""Regression tests for failures observed in the 2026-11-14 edit evaluation."""
import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from engine import Engine, project

NODE = os.environ.get('PHYXI_PTC_TEST_NODE') or shutil.which('node')


class StatefulBackend:
    starts = exits = calls = 0
    def __init__(self, config, folder):
        self.open = False
        self.schemas = {'native-modeling': {}, 'catia-v5': {
            n: {'name': n, 'inputSchema': {'type': 'object'}}
            for n in ('open', 'close', 'transport')}}
    async def __aenter__(self):
        self.owner = asyncio.current_task()
        type(self).starts += 1
        return self
    async def __aexit__(self, *args):
        assert asyncio.current_task() is self.owner
        type(self).exits += 1
    async def call(self, server, tool, args):
        assert asyncio.current_task() is self.owner
        type(self).calls += 1
        if tool == 'transport': raise ConnectionError('disconnected')
        if tool == 'open': self.open = True
        elif tool == 'close':
            if not self.open: return {'isError': True}
            self.open = False
        return {'structuredContent': {'open': self.open}}


@unittest.skipUnless(NODE, 'Node required')
class SessionRegression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        StatefulBackend.starts = StatefulBackend.exits = StatefulBackend.calls = 0
        self.engine = Engine(self.tmp.name, {}, NODE, backend_factory=StatefulBackend)
        self.addAsyncCleanup(self.engine.aclose)

    async def run_code(self, name, code):
        await self.engine.start(name, code)
        await asyncio.gather(*self.engine.tasks)
        return self.engine.status(name)

    async def test_catalog_program_program_retains_sketch_session(self):
        await self.engine.catalog('catia-v5', ['open'])
        a = await self.run_code('a', 'return (await tools.catia_v5.open({})).data;')
        b = await self.run_code('b', 'return (await tools.catia_v5.close({})).data;')
        self.assertEqual(b['status'], 'SUCCEEDED')
        self.assertFalse(b['output']['open'])
        self.assertEqual(a['backend_session_id'], b['backend_session_id'])
        self.assertTrue(b['backend_session_reused'])
        self.assertEqual(StatefulBackend.starts, 1)
        await self.engine.aclose()
        self.assertEqual(StatefulBackend.exits, 1)

    async def test_disconnect_never_reconnects_or_replays(self):
        a = await self.run_code('lost', 'await tools.catia_v5.transport({});')
        self.assertEqual(a['status'], 'UNCERTAIN')
        self.assertEqual((await self.engine.start('new', 'return 1;'))['status'], 'REJECTED_BUSY')
        with self.assertRaises(RuntimeError): await self.engine.catalog('catia-v5', [])
        self.assertEqual(StatefulBackend.starts, 1)
        self.assertEqual(StatefulBackend.calls, 1)

    async def test_parallel_discovery_one_owner_and_closed_engine_no_new_record(self):
        await asyncio.gather(*(self.engine.catalog('catia-v5', []) for _ in range(4)))
        self.assertEqual(StatefulBackend.starts, 1)
        await self.engine.aclose()
        with self.assertRaises(RuntimeError):
            await self.engine.start('after-close', 'return 1;')
        self.assertEqual(self.engine.status('after-close')['status'], 'NOT_FOUND')

    async def test_tolerance_accepts_rounding_rejects_real_error(self):
        r = await self.run_code('near', '''return {
          rounding:cad.near(1262949.1850,1262949.1852,{abs:0.001,rel:1e-8}),
          wrong:cad.near(1262949,1263949,{abs:0.001,rel:1e-8}),
          zero:cad.near(0,0,{abs:0,rel:0})};''')
        self.assertEqual(r['status'], 'SUCCEEDED')
        self.assertTrue(r['output']['rounding']['passed'])
        self.assertFalse(r['output']['wrong']['passed'])
        self.assertTrue(r['output']['zero']['passed'])

    async def test_tolerance_invalid_finite_and_negative_inputs(self):
        r = await self.run_code('bad', '''let rejected=0;
        for(const [a,b,t] of [[NaN,0,{abs:1,rel:0}],[1,1,{abs:-1,rel:0}],
          [1,1,{abs:1}],["1",1,{abs:1,rel:0}],[1,1,{abs:Infinity,rel:0}],
          [1e308,-1e308,{abs:1,rel:0}],[1e308,1,{abs:1,rel:1e308}]]){
          try{cad.near(a,b,t);}catch(e){rejected++;}
        }return rejected;''')
        self.assertEqual(r['output'], 7)


class BusinessFailureRegression(unittest.TestCase):
    def test_false_success_face_and_edge_text(self):
        for kind in ('faces', 'edges'):
            text = f'Could not enumerate {kind}: CATIASelection.Search failed'
            raw = {'structuredContent': {'ok': True, 'plan': {'status': 'SUCCEEDED',
                'steps': [{'tool': 'catia_list_' + kind}], 'results': [{'data': {'text': text}}]}}}
            reply = project(raw)
            self.assertFalse(reply['ok'])
            self.assertFalse(reply['uncertain'])
            self.assertIn('Search failed', reply['error_detail'])

    def test_nested_structured_failure_and_uncertainty(self):
        for completion in ('KNOWN_FINISHED', 'UNCERTAIN'):
            r = project({'structuredContent': {'ok': True, 'plan': {'status': 'SUCCEEDED',
                'steps': [{'tool': 'catia_get_bounding_box'}],
                'results': [{'data': {'ok': False, 'completion': completion, 'message': 'COM_ERROR'}}]}}})
            self.assertFalse(r['ok'])
            self.assertEqual(r['uncertain'], completion == 'UNCERTAIN')

    def test_multi_step_enumeration_failure_propagates(self):
        r = project({'structuredContent': {'plan': {'status': 'SUCCEEDED',
            'steps': [{'tool':'a'},{'tool':'b'}],
            'results': [{'data':{'text':'No open documents'}},
                        {'data':{'text':'Could not enumerate edges: lookup failed'}}]}}})
        self.assertFalse(r['ok'])

    def test_empty_legitimate_result_is_success(self):
        for data in ([], {'text':'No open documents'}, {'text':'No faces found'}, {'count':0}):
            self.assertTrue(project({'structuredContent':data})['ok'])


if __name__ == '__main__': unittest.main()
