"""JSON adapter regression: no credentials, network or CAD writes."""
import sys,json,unittest
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from providers import PROVIDERS,endpoint
from server_chat import parse_reply,wire_messages,request_server,pack_images
from agent import Agent,TOOLS

class Tests(unittest.TestCase):
 def test_explicit_route(self):
  self.assertEqual(endpoint('http://127.0.0.1:8000/v1','qwen3.8-base',PROVIDERS[4]),'http://127.0.0.1:8000/v1/chat/completions')
  for provider in PROVIDERS[:4]:
   with self.assertRaises(ValueError):endpoint('http://127.0.0.1:8000/v1','qwen3.8-base',provider)
  with self.assertRaises(ValueError):endpoint('http://x/v1?key=a','qwen3.8-base',PROVIDERS[4])
 def test_images_preserved_tool_history_preserved(self):
  messages=[{'role':'assistant','tool_calls':[{'function':{'name':'inspect_catia','arguments':'{}'}}]},
   {'role':'tool','content':'{"ok":true}','tool_call_id':'a'},
   {'role':'user','content':[{'type':'text','text':'numeric-data'},{'type':'image_url','image_url':{'url':'data:image/png;base64,aW1hZ2U='}}]}]
  wire,n=wire_messages(messages,TOOLS);s=json.dumps(wire,ensure_ascii=False)
  self.assertEqual(n,1);self.assertIn('aW1hZ2U=',s);self.assertEqual(wire[-1]['content'],messages[-1]['content'])
  self.assertIn('plugin_tool_result',s);self.assertIn('inspect_catia',s)
 def test_invalid_image_rejected_without_text_fallback(self):
  for url in ['https://example.com/a.png','data:image/png;base64,!!','data:image/png;base64,']:
   with self.subTest(url=url),self.assertRaises(ValueError):
    wire_messages([{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}],TOOLS)
 def test_four_image_server_limit_preserves_all_sources(self):
  import base64,hashlib
  from PIL import Image
  from io import BytesIO
  raw=BytesIO();Image.new('RGB',(100,80),'red').save(raw,format='PNG')
  block={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()}}
  wire=[{'role':'user','content':[{'type':'text','text':'read all'},*[block]*5]}]
  packed,count,hashes=pack_images(wire)
  self.assertLessEqual(count,4);self.assertEqual(len(hashes),count)
  labels=[b['text'] for b in packed[0]['content'] if b['type']=='text'][1:]
  self.assertEqual(len(labels),5)
  for i,label in enumerate(labels):self.assertIn(f'IMG{i+1:03d}',label)
  sheets=[Image.open(BytesIO(base64.b64decode(b['image_url']['url'].split(',')[1]))) for b in packed[-1]['content'] if b['type']=='image_url']
  self.assertEqual(sum(im.height//112 for im in sheets),5)
 def test_single_leading_system_for_server_template(self):
  wire,_=wire_messages([{'role':'system','content':'existing rules'},{'role':'user','content':'hi'}],TOOLS)
  self.assertEqual([m['role'] for m in wire],['system','user'])
  self.assertIn('existing rules',wire[0]['content'])
 def test_unknown_and_malformed_calls_rejected(self):
  for value in [[],{'content':'x','other':1},{'tool_calls':[{'name':'shell','arguments':{}}]},
    {'tool_calls':[{'name':'inspect_catia','arguments':{'bad':1}}]},
    {'tool_calls':[{'name':'build_surface','arguments':{}}]},
    {'tool_calls':[{'name':'inspect_catia','arguments':[]}]}, {'content':''}]:
   with self.subTest(value=value),self.assertRaises(ValueError):parse_reply(json.dumps(value),TOOLS)
 def test_request_payload_and_no_reasoning(self):
  def transport(req,provider,timeout):
   body=json.loads(req.data);self.assertEqual(body['temperature'],1.0)
   self.assertEqual(body['max_tokens'],16384);self.assertEqual(body['response_format'],{'type':'json_object'})
   self.assertNotIn('tools',body)
   return BytesIO(json.dumps({'id':'id','model':'qwen3.8-base','usage':{'total_tokens':20},'choices':[{'finish_reason':'stop','message':{'content':'{"content":"ok","tool_calls":[]}','reasoning':'DO NOT SAVE'}}]}).encode())
  with patch('server_chat.open_request',transport):
   r=request_server('http://x/v1','dummy','qwen3.8-base',[],TOOLS,PROVIDERS[4],lambda _:None)
  self.assertNotIn('DO NOT SAVE',json.dumps(r));self.assertFalse(r['response_metadata']['vision_used'])
 def test_truncated_reply_never_executes(self):
  with patch('server_chat.open_request',return_value=BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{"tool_calls":[]}'}}]}).encode())):
   with self.assertRaises(ValueError):request_server('http://x/v1','dummy','qwen3.8-base',[],TOOLS,PROVIDERS[4],lambda _:None)

if __name__=='__main__':unittest.main()
