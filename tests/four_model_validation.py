"""Routing and Responses regression checks; no live credentials or CAD writes."""
import sys,json,unittest,tempfile
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from providers import endpoint,PROVIDERS,MICU_BASE
from responses_api import request_responses,input_items
from controller import Controller

class Tests(unittest.TestCase):
 def test_four_routes_and_gpt_only_reasoning(self):
  for model in ['gpt-6.1-sol','glm-5.3-flash','qwen3.8-max','kimi-k3']:
   with self.subTest(model=model):
    self.assertEqual(endpoint(MICU_BASE,model,PROVIDERS[3]),MICU_BASE+'/responses')
    class Response(BytesIO):headers={'Content-Type':'application/json'}
    def transport(request,provider):
     p=json.loads(request.data);self.assertEqual('include' in p,model.startswith('gpt-'))
     return Response(json.dumps({'status':'completed','model':model,'output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}).encode())
    with tempfile.TemporaryDirectory() as t,patch('responses_api.open_request',transport):
     r=request_responses(MICU_BASE,'test-key',model,[{'role':'user','content':'test'}],[],PROVIDERS[3],Controller(t),lambda _:None)
     self.assertEqual(r['content'],'ok')
 def test_no_cross_provider_or_url_relaxation(self):
  for model in ['qwen3.8-max','kimi-k3']:
   with self.assertRaises(ValueError):endpoint('https://other.example/v1',model,PROVIDERS[3])
   with self.assertRaises(ValueError):endpoint(MICU_BASE,model,PROVIDERS[2])
  with self.assertRaises(ValueError):endpoint(MICU_BASE,'unknown',PROVIDERS[3])
 def test_image_and_tool_replay(self):
  items=input_items([{'role':'tool','tool_call_id':'c1','content':'{"ok":true}'},
   {'role':'user','content':[{'type':'text','text':'image'},{'type':'image_url','image_url':{'url':'data:image/png;base64,TEST'}}]}])
  self.assertEqual(items[0]['call_id'],'c1');self.assertEqual(items[1]['content'][1]['type'],'input_image')
if __name__=='__main__':unittest.main()
