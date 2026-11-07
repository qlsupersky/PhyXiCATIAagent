import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from engine import Engine, project

NODE = os.environ.get('PHYXI_PTC_TEST_NODE', shutil.which('node'))


class FakeBackends:
    dispatches = []
    active = 0
    max_active = 0
    def __init__(self, config, folder):
        self.schemas = {n: {} for n in ('catia-v5', 'native-modeling')}
        self.schemas['catia-v5'] = {n: {'name': n, 'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'integer'}}, 'required': ['id']}}
            for n in ('lookup', 'fail', 'uncertain', 'transport')}
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def call(self, server, tool, args):
        type(self).dispatches.append((tool, args))
        type(self).active += 1
        type(self).max_active = max(type(self).max_active, type(self).active)
        await asyncio.sleep(.01)
        type(self).active -= 1
        if tool == 'transport': raise ConnectionError('lost upstream connection')
        if tool == 'uncertain': return {'structuredContent': {'ok': False, 'status': 'UNCERTAIN', 'completion': 'UNCERTAIN'}}
        if tool == 'fail': return {'isError': True, 'content': [{'type': 'text', 'text': 'known failed'}]}
        return {'content': [{'type': 'text', 'text': json.dumps({'id': args['id'], 'keep': args['id'] % 2 == 0, 'detail': 'x' * 5000})}]}


@unittest.skipUnless(NODE, 'Node runtime required')
class CodeModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        FakeBackends.dispatches = []
        FakeBackends.max_active = FakeBackends.active = 0
        self.engine = Engine(self.tmp.name, {}, NODE, backend_factory=FakeBackends)

    async def run_program(self, code, name='test'):
        await self.engine.start(name, code)
        await asyncio.wait_for(asyncio.gather(*self.engine.tasks), 45)
        return self.engine.status(name)

    async def test_loop_branch_and_compression(self):
        result = await self.run_program('const keep=[]; for(let i=0;i<6;i++){const r=await tools.catia_v5.lookup({id:i}); if(r.data.keep) keep.push(r.data.id);} return {keep};')
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(result['output'], {'keep': [0,2,4]})
        self.assertEqual(result['calls'], 6)
        self.assertGreater(result['raw_tool_bytes'], 30000)
        self.assertLess(result['guest_result_bytes'], 100)

    async def test_duplicate_no_replay_and_changed_code_refused(self):
        code = 'await tools.catia_v5.lookup({id:1});return 1;'
        await self.run_program(code)
        again = await self.engine.start('test', code)
        self.assertTrue(again['cached_no_dispatch'])
        self.assertEqual(len(FakeBackends.dispatches), 1)
        with self.assertRaises(ValueError): await self.engine.start('test', 'return 2;')

    async def test_no_guest_os_or_network_apis(self):
        result = await self.run_program('return [typeof process, typeof require, typeof fetch, typeof WebSocket];')
        self.assertEqual(result['output'], ['undefined'] * 4)
        self.assertEqual(result['calls'], 0)

    async def test_constructor_is_guest_not_node_escape(self):
        result = await self.run_program('return tools.catia_v5.lookup.constructor("return typeof process")();')
        self.assertEqual(result['output'], 'undefined')

    async def test_infinite_loop_interrupts(self):
        result = await self.run_program('while(true){}')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['calls'], 0)

    async def test_memory_limited(self):
        result = await self.run_program('const x=[];while(true)x.push(new Array(10000).fill("large-value"));')
        self.assertEqual(result['status'], 'FAILED')

    async def test_final_output_bound(self):
        result = await self.run_program('return "x".repeat(20000);')
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('output', result)

    async def test_invalid_schema_no_dispatch(self):
        result = await self.run_program('return await tools.catia_v5.lookup({id:"wrong"});')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(FakeBackends.dispatches, [])

    async def test_failed_call_stops_even_if_caught(self):
        result = await self.run_program('try{await tools.catia_v5.fail({id:0});}catch(e){} try{await tools.catia_v5.lookup({id:1});}catch(e){} return "claimed success";')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual([x[0] for x in FakeBackends.dispatches], ['fail'])

    async def test_uncertain_blocks_new_program(self):
        result = await self.run_program('await tools.catia_v5.uncertain({id:0});')
        self.assertEqual(result['status'], 'UNCERTAIN')
        self.assertEqual((await self.engine.start('other', 'return 1;'))['status'], 'REJECTED_BUSY')

    async def test_transport_failure_is_uncertain(self):
        result = await self.run_program('await tools.catia_v5.transport({id:0});')
        self.assertEqual(result['status'], 'UNCERTAIN')

    async def test_fanout_serialized(self):
        result = await self.run_program('return (await Promise.all([0,1,2].map(id=>tools.catia_v5.lookup({id})))).map(x=>x.data.id);')
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(result['output'], [0,1,2])
        self.assertEqual(FakeBackends.max_active, 1)

    async def test_host_only_known_servers(self):
        result = await self.run_program('return await mcp.call("filesystem","read",{});')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(FakeBackends.dispatches, [])

    async def test_unawaited_call_does_not_claim_success(self):
        result = await self.run_program('tools.catia_v5.lookup({id:1});return 42;')
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('output', result)

    async def test_call_budget(self):
        result = await self.run_program('for(let i=0;i<105;i++) await tools.catia_v5.lookup({id:i}); return 42;')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(len(FakeBackends.dispatches), 100)

    def test_legacy_double_encoded_document_list(self):
        value = project({'content': [{'type':'text','text':json.dumps(json.dumps([{'name':'Part'}]))}]})
        self.assertEqual(value['data'], [{'name':'Part'}])


if __name__ == '__main__':
    unittest.main()
