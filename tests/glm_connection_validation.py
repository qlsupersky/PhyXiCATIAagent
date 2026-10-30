"""GLM routing and explicit CC Switch pinning without network or live credentials."""
import sys,json,sqlite3,tempfile,unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from providers import endpoint,PROVIDERS,MICU_BASE
from cc_switch import load_micu
from responses_api import request_responses
from controller import Controller

class Tests(unittest.TestCase):
 def test_glm_omits_gpt_only_include(self):
  class Response(BytesIO):headers={'Content-Type':'application/json'}
  def transport(request,provider):
   payload=json.loads(request.data)
   self.assertNotIn('include',payload)
   self.assertEqual(payload['model'],'glm-5.3-flash')
   return Response(json.dumps({'status':'completed','model':'glm-5.3-flash','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}).encode())
  with tempfile.TemporaryDirectory() as t,patch('responses_api.open_request',transport):
   r=request_responses(MICU_BASE,'test-key','glm-5.3-flash',[{'role':'user','content':'test'}],[],PROVIDERS[3],Controller(t),lambda _:None)
   self.assertEqual(r['content'],'ok')
 def test_glm_uses_micu_responses(self):
  self.assertEqual(endpoint(MICU_BASE,'glm-5.3-flash',PROVIDERS[3]),MICU_BASE+'/responses')
  with self.assertRaises(ValueError):endpoint('https://other.example/v1','glm-5.3-flash',PROVIDERS[3])
  with self.assertRaises(ValueError):endpoint('https://api.openai.com/v1','glm-5.3-flash',PROVIDERS[2])
 def test_pin_never_switches_or_falls_back(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'switch.db';c=sqlite3.connect(p)
   c.execute('CREATE TABLE providers(id TEXT,app_type TEXT,is_current INTEGER,settings_config TEXT)')
   for i,model,current in [('coding','gpt-6.1-sol',1),('catia','glm-5.3-flash',0)]:
    cfg=f'model="{model}"\nmodel_provider="custom"\n[model_providers.custom]\nbase_url="{MICU_BASE}"\nwire_api="responses"'
    s={'auth':{'OPENAI_API_KEY':i+'-test-key'},'config':cfg}
    c.execute('INSERT INTO providers VALUES(?,?,?,?)',(i,'codex',current,json.dumps(s)))
   c.commit();c.close();before=p.read_bytes()
   self.assertEqual(load_micu(p,provider_id='catia')['model'],'glm-5.3-flash')
   self.assertEqual(load_micu(p)['model'],'gpt-6.1-sol')
   with self.assertRaises(ValueError):load_micu(p,provider_id='missing')
   self.assertEqual(before,p.read_bytes())

if __name__=='__main__':unittest.main()
