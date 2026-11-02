"""Optional upstream contract checks; no CATIA COM calls are dispatched."""
import asyncio
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catia_adapter import make_server


@unittest.skipUnless(os.environ.get('PHYXI_TEST_CATIA_UPSTREAM'), 'set PHYXI_TEST_CATIA_UPSTREAM to the deployed upstream source')
class AdapterContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        base = Path(os.environ['PHYXI_TEST_WORK']); base.mkdir(parents=True, exist_ok=True)
        os.environ['CATIA_MCP_LOG_FILE'] = str(base / 'adapter-offline.log')
        self.temp = tempfile.TemporaryDirectory(dir=base); self.root = Path(self.temp.name)
        self.server = make_server(os.environ['PHYXI_TEST_CATIA_UPSTREAM'], self.root, self.root / 'gate.sqlite')

    async def asyncTearDown(self):
        await self.server.close()
        self.temp.cleanup()

    async def test_original_schemas_and_compact_catalog(self):
        result = await self.server.call_tool('catia_plan_catalog', {})
        data = result.structuredContent
        self.assertEqual(len(data['tools']), 101)
        self.assertEqual(len(self.server.original_schemas), 98)
        self.assertNotIn('inputSchema', data['tools'][0])
        selected = await self.server.call_tool('catia_plan_catalog', {'names':['catia_pad'], 'include_schema':True})
        self.assertEqual(selected.structuredContent['tools'][0]['inputSchema'], self.server.original_schemas['catia_pad'])
        self.assertEqual(data['adapter']['version'], '0.7.0')

    async def test_status_validates_without_dispatch(self):
        self.server.plans.dispatch = lambda n,a:self.fail('dispatched')
        result = await self.server.call_tool('catia_plan_status', {'request_id':{}})
        self.assertTrue(result.isError)
        self.assertEqual(self.server.plans.gate.snapshot()['status'], 'IDLE')

    async def test_native_mcp_image_is_preserved(self):
        data = base64.b64encode(b'image-fixture').decode()
        self.server.plans.dispatch = lambda n,a:{'content':[{'type':'image','mimeType':'image/png','data':data}]}
        result = self.server._execute_tool('catia_plan_run', {'request_id':'image-fixture','steps':[{'id':'image','tool':'catia_list_documents'}]})
        self.assertTrue(result.structuredContent['ok'])
        self.assertEqual(result.content[-1].type, 'image')
        self.assertEqual(result.content[-1].data, data)

    async def test_runtime_value_error_keeps_uncertainty(self):
        def crash(n,a): raise ValueError('after dispatch')
        self.server.plans.dispatch = crash
        with self.assertRaises(ValueError):
            self.server._execute_tool('catia_plan_run', {'request_id':'runtime-fixture','steps':[{'id':'one','tool':'catia_list_documents'}]})
        self.assertEqual(self.server.plans.gate.snapshot()['status'], 'FROZEN')


if __name__ == '__main__': unittest.main()
