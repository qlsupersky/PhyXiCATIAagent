"""Meaningful image-boundary regressions. No network or CAD dispatch."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_images import ImageInput, manifest, prompt_body, verify_stored, load_snapshot, input_hash, from_path
from native_workflow import NativeWorkflow, proposal_hash

def image(color='red'):
    out=io.BytesIO();Image.new('RGB',(32,24),color).save(out,format='PNG')
    return ImageInput(out.getvalue(),'image/png','reference.png')

class Images(unittest.TestCase):
    def setUp(self):
        root=Path(os.environ['PHYXI_TEST_WORK']);root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_stored_image_resizing_or_substitution_rejected(self):
        im=image();body,_=prompt_body('describe', [im])
        rows=[{'id':'user','type':'user','text':'describe','files':[{'mime':'image/png','data':base64.b64encode(im.data).decode(),'source':{'type':'inline'}}]},
              {'id':'assistant','type':'assistant','model':{'providerID':'phyxi-deepseek','id':'deepseek-flash'},'finish':'stop'}]
        self.assertEqual(verify_stored(rows,body)['images_persisted'][0]['bytes'],len(im.data))
        changed=copy.deepcopy(rows);changed[0]['files'][0]['data']=base64.b64encode(image('blue').data).decode()
        with self.assertRaises(ValueError):verify_stored(changed,body)
        changed=copy.deepcopy(rows);changed[1]['model']['id']='other'
        with self.assertRaises(ValueError):verify_stored(changed,body)

    def test_corrupt_oversized_mislabelled_and_path_rejected(self):
        for im in [ImageInput(b'not image','image/png','bad.png'),
                   ImageInput(image().data,'image/jpeg','wrong.jpg'),
                   ImageInput(image().data,'image/png','../escape.png')]:
            with self.assertRaises(ValueError):manifest([im])
        with self.assertRaises(ValueError):manifest([image()]*5)
        with self.assertRaises(ValueError):manifest([ImageInput(image().data+b'0'*(8*1024*1024),'image/png','large.png')])

    def test_changed_reference_blocks_approval_before_prepare(self):
        workflow=NativeWorkflow(self.root)
        source=workflow.fresh('proposal');(source/'attachments').mkdir(parents=True)
        im=image();refs=manifest([im]);(source/'image-manifest.json').write_text(json.dumps(refs))
        (source/'attachments/1.bin').write_bytes(im.data)
        proposal={'summary':'fixture','macro_ascii':'fixture','checks':{}}
        record={'requirement':'fixture','proposal':proposal,'folder':str(source),'source_session':'fixture',
                'reference_images':refs,'input_sha256':input_hash('fixture',refs)}
        self.assertEqual(load_snapshot(source,refs),[im])
        (source/'attachments/1.bin').write_bytes(image('blue').data)
        with patch.object(workflow.service,'prepare',side_effect=AssertionError('must not prepare')):
            with self.assertRaises(ValueError):workflow.approve(record,{},proposal_hash(proposal))
        self.assertEqual(workflow.service.snapshot()['status'],'IDLE')

    def test_changed_text_blocks_approval(self):
        workflow=NativeWorkflow(self.root)
        proposal={'summary':'fixture','macro_ascii':'fixture','checks':{}}
        record={'requirement':'changed','proposal':proposal,'reference_images':[],
                'input_sha256':input_hash('original',[])}
        with patch.object(workflow.service,'prepare',side_effect=AssertionError('must not prepare')):
            with self.assertRaises(ValueError):workflow.approve(record,{},proposal_hash(proposal))

    def test_sketch_in_shape_checks_rejected_before_bridge_compile(self):
        from native_contract import validate_program_checks
        code='Language="VBSCRIPT"\nSub CATMain(runId, outputPath, resultPath)\nSet doc=CATIA.Documents.Add("Part")\nSet part=doc.Part\nSet body=part.MainBody\nbody.Name="Own_" & runId\nSet sk=body.Sketches.Add(part.OriginElements.PlaneXY)\nsk.Name="BaseSketch"\nEnd Sub\n'
        checks={'features':[{'name':'BaseSketch'}],'sketch_count':1,'volume_mm3':None}
        with self.assertRaises(ValueError):validate_program_checks(code,checks)

    def test_http_timeout_never_resubmits_image(self):
        workflow=NativeWorkflow(self.root);runtime=workflow.runtime
        calls=[]
        def api(method,path,body=None,**kwargs):
            calls.append((method,path))
            if path=='/api/session':return {'data':{'id':'fixture'}}
            if method=='POST':raise TimeoutError('delivery uncertain')
            return {'data':[]}
        with patch.object(runtime,'api',side_effect=api):
            with self.assertRaises(RuntimeError):runtime.prompt('fixture',self.root/'one-shot',timeout=0,images=[image()])
        self.assertEqual(sum(method=='POST' and path.endswith('/prompt') for method,path in calls),1)
        self.assertTrue((self.root/'one-shot/post-unconfirmed.json').exists())

    def test_actual_2000px_limit_normalizes_with_provenance(self):
        source=self.root/'wide.jpg';Image.new('RGB',(2074,908),'blue').save(source)
        normalized=from_path(source);info=manifest([normalized])[0]
        from native_contract import sha
        self.assertLessEqual(max(info['size']),1920)
        self.assertEqual(info['source_size'],[2074,908])
        self.assertEqual(info['source_sha256'],sha(source.read_bytes()))
        self.assertNotEqual(info['sha256'],info['source_sha256'])
        folder=self.root/'snapshot';(folder/'attachments').mkdir(parents=True)
        (folder/'image-manifest.json').write_text(json.dumps([info]))
        (folder/'attachments/1.bin').write_bytes(normalized.data)
        self.assertEqual(load_snapshot(folder,[info]),[normalized])

    def test_explicit_HTTP_rejection_stops_without_poll_or_replay(self):
        from native_runtime import OpenCodeRequestRejected
        runtime=NativeWorkflow(self.root).runtime;calls=[]
        def api(method,path,body=None,**kwargs):
            calls.append((method,path))
            if path=='/api/session':return {'data':{'id':'fixture'}}
            raise OpenCodeRequestRejected(400)
        with patch.object(runtime,'api',side_effect=api):
            with self.assertRaises(OpenCodeRequestRejected):runtime.prompt('fixture',self.root/'rejected',images=[image()])
        self.assertEqual(calls,[('POST','/api/session'),('POST','/api/session/fixture/prompt')])
        self.assertEqual(json.loads((self.root/'rejected/post-unconfirmed.json').read_text())['HTTP'],400)

    def history_fixture(self, complete):
        from test_native_core import fixture, MACRO
        service,job=fixture(self.root)
        workflow=NativeWorkflow(self.root,self.root/'gate.sqlite')
        if complete:
            service.reserve(job);claim=service.claim(job,MACRO);service.finish(job,claim['owner'],{'offline_fixture':True})
        folder=workflow.fresh('execution');folder.mkdir()
        (folder/'session.json').write_text(json.dumps({'id':'old-engine-session'}))
        calls=[{'tool':'native-modeling.modeling_run','status':'completed','input':{'job_id':job,'macro_ascii':MACRO}}]
        messages={'data':[{'type':'idle','outcome':'succeeded'},
                 {'type':'assistant','content':[{'type':'tool','state':{'metadata':{'toolCalls':calls}}}]}]}
        (folder/'messages.json').write_text(json.dumps(messages))
        (service.folder(job)/'execution-session.json').write_text(json.dumps({'folder':str(folder)}))
        workflow.runtime.auth={'offline_fixture':True}
        return workflow,job

    def test_upgrade_history_accepts_verified_completed_local_evidence(self):
        from native_runtime import OpenCodeRequestRejected
        workflow,job=self.history_fixture(True)
        with patch.object(workflow.runtime,'api',side_effect=OpenCodeRequestRejected(404)), \
             patch.object(workflow.service,'run',side_effect=AssertionError('never replay')):
            result=workflow.refresh(job)
        self.assertEqual(result['state'],'SUCCEEDED')
        self.assertTrue(result['model_MCP_audit']['model_MCP_call_verified'])
        self.assertTrue((workflow.service.folder(job)/'history-refresh-local-evidence.json').exists())

    def test_upgrade_missing_session_never_promotes_pending_job(self):
        from native_runtime import OpenCodeRequestRejected
        workflow,job=self.history_fixture(False)
        with patch.object(workflow.runtime,'api',side_effect=OpenCodeRequestRejected(404)):
            with self.assertRaises(OpenCodeRequestRejected):workflow.refresh(job)
        self.assertEqual(workflow.service.job(job)['state'],'APPROVED')

if __name__=='__main__':unittest.main()
