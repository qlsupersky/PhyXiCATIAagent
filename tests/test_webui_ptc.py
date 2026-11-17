import json
import unittest
from webui_ptc import profile, connect_ptc

class ProfileTests(unittest.TestCase):
    def test_ptc_only_and_no_embedded_credentials(self):
        p=profile('https://example.test/v1','python','server','backends','node')
        self.assertEqual(p['model'],'phyxi-glm/glm-5.3-flash')
        self.assertTrue(p['mcp']['catia-code']['enabled'])
        self.assertEqual(set(p['mcp']),{'catia-code'})
        self.assertEqual(p['providers']['phyxi-glm']['settings']['apiKey'],'{env:PHYXI_GLM_API_KEY}')
        self.assertNotIn('sk-',json.dumps(p))

    def test_reconnect_button_does_not_replace_connected_ptc(self):
        class Link:
            def __init__(self):self.calls=[]
            def api(self,method,path,*args,**kw):
                self.calls.append((method,path))
                return {'data':[{'name':'catia-code','status':{'status':'connected'}}]}
        link=Link();connect_ptc(link,{})
        self.assertTrue(all(m=='GET' for m,p in link.calls))

    def test_failed_connection_is_not_implicitly_replayed(self):
        class Link:
            def api(self,method,path,*args,**kw):
                if method!='GET':raise AssertionError('Must not reconnect')
                return {'data':[{'name':'catia-code','status':{'status':'failed'}}]}
        with self.assertRaises(RuntimeError):connect_ptc(Link(),{})

if __name__=='__main__': unittest.main()
