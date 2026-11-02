import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opencode_link import OpenCodeLink
from web_backend import WebBackend, present
from web_server import create_server


class Fake:
    def __init__(self, root):
        self.project=root; self.session='ses_web'; self.url='http://127.0.0.1:1'; self.calls=0
        self.entered=threading.Event();self.release=threading.Event()
        self.pending=root/'pending.json'
    def _ensure_idle(self): return []
    def _pending(self): return self.pending
    def switch(self,*args): pass
    def send(self,text,files,cancel,observe):
        self.calls+=1
        self.pending.write_text(json.dumps({'message_id':'msg_web'}))
        observe([{'id':'msg_web','type':'user','text':text}]); self.entered.set()
        self.release.wait(4)
        if cancel.is_set(): raise RuntimeError('wait stopped')
        self.pending.unlink()
        return {'outcome':'succeeded','message_id':'msg_web','attachments_verified':[], 'messages':[{'id':'msg_web','type':'user','text':text}]}


class WebTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ['PHYXI_TEST_WORK']);base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
        self.fake=Fake(self.root);self.backend=WebBackend(self.root,link=self.fake)
    def tearDown(self):
        self.fake.release.set()
        for _ in range(100):
            if not self.backend.active:break
            time.sleep(.01)
        self.temp.cleanup()

    def test_duplicate_http_send_does_not_submit_twice(self):
        self.backend.send('one','hello')
        self.assertTrue(self.fake.entered.wait(2))
        self.assertTrue(self.backend.send('one','hello')['cached_no_resubmit'])
        self.assertEqual(self.fake.calls,1)
        with self.assertRaises(ValueError):self.backend.send('one','changed')

    def test_switch_refresh_new_blocked_during_send(self):
        self.backend.send('one','hello');self.assertTrue(self.fake.entered.wait(2))
        with self.assertRaises(ValueError):self.backend.refresh()
        with self.assertRaises(ValueError):self.backend.select('ses_other')
        with self.assertRaises(ValueError):self.backend.new()

    def test_restart_receipt_never_replays(self):
        self.backend.send('one','hello');self.assertTrue(self.fake.entered.wait(2))
        restored=WebBackend(self.root,link=Fake(self.root))
        self.assertEqual(restored.send('one','hello')['status'],'NEEDS_REFRESH')
        self.assertEqual(restored.link.calls,0)

    def test_stop_waiting_preserves_pending(self):
        self.backend.send('one','hello');self.assertTrue(self.fake.entered.wait(2))
        self.backend.stop_waiting();self.fake.release.set()
        for _ in range(100):
            if not self.backend.active:break
            time.sleep(.01)
        self.assertEqual(self.backend.job('one')['status'],'NEEDS_REFRESH')
        self.assertTrue(self.fake.pending.exists())

    def test_binary_attachments_not_exposed_in_view(self):
        value=present([{'id':'u','type':'user','text':'hi','files':[{'name':'x.png','data':'secret-binary'}]}])
        self.assertNotIn('secret-binary',json.dumps(value))

    def test_refresh_consumed_by_other_frontend_settles_exact_receipt_only(self):
        evidence=self.root/'turn';evidence.mkdir()
        (evidence/'result.json').write_text(json.dumps({'session':'ses_web','message_id':'msg_web','outcome':'succeeded'}))
        job={'session':'ses_web','message_id':'msg_web','status':'NEEDS_REFRESH','evidence_folder':str(evidence)}
        OpenCodeLink._write(self.backend.folder/'one.json',job)
        OpenCodeLink._write(self.backend.folder/'other.json',{**job,'message_id':'msg_different'})
        self.backend.reconcile_jobs({})
        self.assertEqual(self.backend.job('one')['status'],'SUCCEEDED')
        self.assertEqual(self.backend.job('other')['status'],'NEEDS_REFRESH')

    def test_tool_structured_feedback_and_failure_visible(self):
        feedback={'ok':False,'plan':{'status':'FAILED'}}
        rows=[{'id':'a','type':'assistant','content':[{'id':'p','type':'tool','name':'execute','state':{'status':'completed','output':json.dumps(feedback),'metadata':{'toolCalls':[{'tool':'catia-v5.catia_plan_run'}]}}}]}]
        value=present(rows)['tools'][0]
        self.assertEqual(value['feedback'],feedback)
        self.assertEqual(value['name'],'catia-v5.catia_plan_run')

    def test_invalid_file_path_and_bad_base64_rejected(self):
        for name,data in [('../x','YQ=='),('x','!!!!')]:
            with self.assertRaises(ValueError):self.backend.attachments([{'name':name,'data':data}])

    def test_http_auth_origin_and_static_path_boundary(self):
        server,token=create_server(self.backend)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def request(route,auth=None,origin=None):
            headers={}
            if auth:headers['Authorization']='Bearer '+auth
            if origin:headers['Origin']=origin
            return urllib.request.urlopen(urllib.request.Request(base+route,headers=headers),timeout=3)
        try:
            with self.assertRaises(urllib.error.HTTPError) as err:request('/api/state')
            self.assertEqual(err.exception.code,401)
            with self.assertRaises(urllib.error.HTTPError) as err:request('/api/state',token,'https://other.example')
            self.assertEqual(err.exception.code,401)
            with request('/api/state',token) as r:self.assertEqual(json.load(r)['version'],'0.7.0')
            with request('/') as r:
                self.assertIn("script-src 'self'",r.headers['Content-Security-Policy'])
                self.assertNotIn(token,r.read().decode())
            with self.assertRaises(urllib.error.HTTPError) as err:request('/../config.json')
            self.assertEqual(err.exception.code,404)
        finally:server.shutdown();server.server_close();worker.join(3)


if __name__ == '__main__':unittest.main()
