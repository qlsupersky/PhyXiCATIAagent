import hashlib
from pathlib import Path
import tempfile
import unittest
from feedback import native_feedback, content_for_status, finalize_feedback
from engine import project
import asyncio
import os
import shutil
from engine import Engine


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = 'native-' + '1' * 24
        folder = self.root / 'native-modeling/jobs' / self.job
        folder.mkdir(parents=True)
        self.image = folder / 'FAILED-CANDIDATE.jpg'
        self.image.write_bytes(b'fake-image-data-for-binding-test')
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        self.data = {'job_id': self.job, 'state': 'FAILED', 'completion': 'KNOWN_FINISHED',
            'reason': 'geometry_validation_failed',
            'readback': {'volume_mm3': 500, 'expected_volume_mm3': 1000, 'passed': False},
            'diagnostic': {'image': str(self.image), 'image_sha256': hashlib.sha256(self.image.read_bytes()).hexdigest()}}

    def test_bound_failed_image_and_measured_delta(self):
        f = native_feedback(self.data, self.root, self.evidence)
        self.assertTrue(f['image_available'])
        self.assertEqual(f['volume_delta_mm3'], -500)
        self.assertFalse(f['passed'])
        record = {'status': 'FAILED', 'feedback': f, 'evidence_directory': str(self.evidence)}
        self.assertEqual(len(content_for_status(record, True).content), 2)
        self.assertEqual(len(content_for_status(record, False).content), 1)

    def test_arbitrary_path_and_hash_refused(self):
        self.data['diagnostic']['image'] = str(self.root / 'other.jpg')
        self.assertFalse(native_feedback(self.data, self.root, self.evidence)['image_available'])
        self.data['diagnostic']['image'] = str(self.image)
        self.data['diagnostic']['image_sha256'] = 'wrong'
        self.assertFalse(native_feedback(self.data, self.root, self.evidence)['image_available'])

    def test_modified_feedback_image_not_returned(self):
        f = native_feedback(self.data, self.root, self.evidence)
        (self.evidence / 'feedback.jpg').write_bytes(b'changed')
        self.assertEqual(len(content_for_status({'feedback':f,'evidence_directory':str(self.evidence)},True).content),1)

    def test_uncertain_advice_no_repair(self):
        f = finalize_feedback({'status':'UNCERTAIN'})
        self.assertFalse(f['automatic_retry'])
        self.assertIn('do not dispatch repair', f['next_action'])

    def test_null_readback_script_failure_remains_known(self):
        reply = project({'structuredContent': {'state':'FAILED','completion':'KNOWN_FINISHED','readback':None}})
        self.assertFalse(reply['ok'])
        self.assertFalse(reply['uncertain'])

    def test_reopen_failure_never_passes(self):
        self.assertFalse(project({'structuredContent':{'readback':{'passed':True},'reopened_readback':{'passed':False}}})['ok'])

    def test_prescreen_error_text_is_compact_and_visible(self):
        r=project({'isError':True,'content':[{'type':'text','text':'Error executing tool: ownership marker missing '+('x'*2000)}]})
        self.assertIn('ownership marker missing',r['error_detail'])
        self.assertLessEqual(len(r['error_detail']),1200)
        f=finalize_feedback({'status':'FAILED','upstream_failure':{'message':r['error_detail']}})
        self.assertIn('ownership marker missing',f['upstream_failure']['message'])

    def test_observed_uncertain_advice_never_suggests_repair(self):
        self.assertIn('do not dispatch repair', finalize_feedback({'status':'FAILED','observed_upstream_uncertain':True})['next_action'])


class StatusBackend:
    def __init__(self, config, folder):
        self.schemas={'native-modeling':{'modeling_status':{'inputSchema':{'type':'object'}}},'catia-v5':{}}
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def call(self,*args):
        return {'structuredContent':{'state':'FROZEN','completion':'UNCERTAIN','CAD_dispatch':False}}


@unittest.skipUnless(os.environ.get('PHYXI_PTC_TEST_NODE') or shutil.which('node'),'Node required')
class ReadOnlyStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_read_does_not_become_unknown_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(folder,{},os.environ.get('PHYXI_PTC_TEST_NODE') or shutil.which('node'),backend_factory=StatusBackend)
            await engine.start('observe','await tools.native_modeling.modeling_status({});')
            await asyncio.gather(*engine.tasks)
            r=engine.status('observe')
            self.assertEqual(r['status'],'FAILED')
            self.assertTrue(r['observed_upstream_uncertain'])
            self.assertFalse(r['upstream_uncertain'])
            await engine.start('second','return {observationOnly:true};')
            await asyncio.gather(*engine.tasks)
            self.assertEqual(engine.status('second')['status'],'SUCCEEDED')


if __name__ == '__main__': unittest.main()
