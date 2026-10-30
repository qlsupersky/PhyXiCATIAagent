"""Real CATIA GSD integration; GPT SSE is deterministic and intercepted in this test only."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(ROOT))
from controller import Controller, save_json
from agent import Agent
from providers import endpoint, PROVIDERS, NoRedirect
from surfaces import validate, review_sources
from surface_quality import seam_metrics


def negative_controls():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln,gp_Pnt,gp_Dir
    left=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,0),gp_Dir(0,0,1)),0,10,0,10).Face()
    tilt=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,0),gp_Dir(.34202014,0,.93969262)),0,10,0,10).Face()
    gap=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,1),gp_Dir(0,0,1)),0,10,0,10).Face()
    a,b=seam_metrics(left,tilt),seam_metrics(left,gap)
    assert a['sampled_g0'] and not a['sampled_g1'] and not a['sampled_g2']
    assert abs(a['max_normal_angle_deg']-20)<1e-4
    assert not b['sampled_g0'] and not b['sampled_g1'] and not b['sampled_g2']
    return {'ok':True,'tilted_20deg':a,'separated_1mm':b}


def gpt_simulated(controller):
    requests,approvals,transcript=[],[],[]
    class Response(BytesIO):
        headers={'Content-Type':'text/event-stream'}
    def intercept(request,provider):
        assert provider==PROVIDERS[2]
        assert request.full_url=='https://api.openai.com/v1/chat/completions'
        payload=json.loads(request.data)
        assert payload['model']=='gpt-4.1' and payload['stream'] is True
        assert any(t['function']['name']=='build_surface' for t in payload['tools'])
        requests.append(payload)
        if len(requests)==1:
            chunks=[{'tool_calls':[{'index':0,'id':'roof-demo','function':{'name':'build_sur','arguments':'{"template":'}}]},
                    {'tool_calls':[{'index':0,'function':{'name':'face','arguments':'"roof"}'}}]}]
        else:
            assert any(m['role']=='tool' for m in payload['messages'])
            chunks=[{'content':'顶盖演示操作已完成；不能据此宣称A级曲面达标。'}]
        raw=''.join('data: '+json.dumps({'choices':[{'delta':c}]})+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        return Response(raw.encode())
    def approve(name,args):
        assert name=='build_surface'
        assert args['all_parameters_mm']['RoofLength']==1800
        assert args['native_builder_source'] and args['generator_source']
        approvals.append(name)
        return True
    agent=Agent(controller,transcript.append,approve,lambda:'')
    with patch('agent.open_request',intercept):
        agent.send('模拟GPT协议：创建顶盖演示曲面，先给出确认方案。','https://api.openai.com/v1','simulator-placeholder',
                   'gpt-4.1',{},provider=PROVIDERS[2])
    tools=[json.loads(m['content']) for m in agent.messages if m['role']=='tool']
    assert len(tools)==1 and tools[0]['ok'],tools
    assert len(requests)==2 and approvals==['build_surface']
    return {'ok':True,'real_gpt_tested':False,'network_requests':0,'protocol':'in-process deterministic SSE, test-only transport interception',
            'actual_catia':True,'approval':True,'transcript':''.join(transcript),'result':tools[0]['result']}


def native_check(result):
    import win32com.client
    app=win32com.client.GetActiveObject('CATIA.Application')
    target=Path(result['native']['catpart'])
    doc=next(app.Documents.Item(i) for i in range(1,app.Documents.Count+1)
             if str(app.Documents.Item(i).FullName).lower()==str(target).lower())
    part=doc.Part
    for name,value in result['parameters'].items():
        assert abs(part.Parameters.Item(name).Value-value)<1e-6,(name,value)
    assert part.Relations.Count>=135
    assert part.HybridBodies.Item('V2_SurfaceDemo').HybridShapes.Count>=6
    q=result['quality']
    assert q['operations_passed'] and q['seam']['sampled_g2']
    assert q['offset']['passed'] and not result['class_a_accepted']
    if result['template']=='roof':
        coordinate=part.HybridBodies.Item('V2_Construction').HybridShapes.Item('Point_0_0').X.Value
        assert abs(coordinate+result['parameters']['RoofLength']/2)<1e-6
    else:
        coordinate=part.HybridBodies.Item('V2_Construction').HybridShapes.Item('Point_2_4').Y.Value
        assert abs(coordinate-result['parameters']['Bulge']-result['parameters']['EdgeRise']/2)<1e-6
    return {'ok':True,'relations':part.Relations.Count,'named_parameters_verified':len(result['parameters']),
            'formula_driven_coordinate_mm':coordinate,'native_history':True}


def main():
    import pythoncom
    pythoncom.CoInitialize()
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True,type=Path)
    args=parser.parse_args()
    args.workspace.mkdir(parents=True,exist_ok=False)
    controller=Controller(args.workspace)
    report={'version':'0.3.0','checks':{},'real_gpt_tested':False,'class_a_accepted':False}
    def record(name,value):
        report['checks'][name]=value
        save_json(args.workspace/'validation.json',report)
        print('PASS',name,flush=True)
    assert endpoint('https://api.openai.com/v1','gpt-4.1',PROVIDERS[2]).endswith('/chat/completions')
    for url,model,provider in [('http://127.0.0.1/v1','gpt-4.1',PROVIDERS[2]),
                               ('https://api.openai.com/v1','gpt-4.1',PROVIDERS[1]),
                               ('https://api.openai.com/v1','glm-test',PROVIDERS[2])]:
        try: endpoint(url,model,provider); raise AssertionError('bad provider accepted')
        except ValueError: pass
    try: NoRedirect().redirect_request(None,None,302,'',{},'https://example.com'); raise AssertionError('redirect allowed')
    except RuntimeError: pass
    record('provider-policies',{'ok':True,'gpt_explicitly_allowed':True,'no_cross_provider_fallback':True,'redirect_blocked':True})
    record('continuity-negative-controls',negative_controls())
    before=controller.info()['path']
    for values in [{'OffsetDistance':0},{'Bulge':float('nan')},{'Unknown':1},[]]:
        try: controller.build_surface('fender',values); raise AssertionError('bad parameters accepted')
        except ValueError: pass
    try: controller.build_surface('roof',expected_sha256='invalid'); raise AssertionError('stale review accepted')
    except ValueError: pass
    denied=Agent(controller,lambda _:None,lambda *_:False,lambda:'')
    assert not denied.execute('build_surface',{'template':'roof'})['ok']
    assert not list((args.workspace/'surfaces').glob('*'))
    assert controller.info()['path']==before
    record('rejections-before-mutation',{'ok':True,'bad_parameters':True,'source_hash_mismatch':True,'approval_denied':True})
    simulated=gpt_simulated(controller)
    roof=simulated['result']
    simulated['native_check']=native_check(roof)
    record('simulated-gpt-real-roof',simulated)
    def edit(template,original,parameters):
        path=Path(original['native']['catpart'])
        oldhash=hashlib.sha256(path.read_bytes()).hexdigest()
        revised=controller.build_surface(template,parameters,original['manifest'],review_sources(ROOT)[0])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==oldhash
        assert revised['quality']['geometry']['Loft']['area_mm2']!=original['quality']['geometry']['Loft']['area_mm2']
        return {'ok':True,'original_file_unchanged':True,'native_check':native_check(revised),'result':revised}
    record('roof-native-parameter-edit',edit('roof',roof,{'RoofLength':1900,'LongCrown':100}))
    fender=controller.build_surface('fender',expected_sha256=review_sources(ROOT)[0])
    record('fender-native-build',{'ok':True,'native_check':native_check(fender),'result':fender})
    record('fender-native-parameter-edit',edit('fender',fender,{'Bulge':80}))
    record('snapshot-gsd',{'ok':bool(controller.info()['hybrid_bodies'])})
    report['ok']=True
    save_json(args.workspace/'validation.json',report)


if __name__=='__main__':main()
