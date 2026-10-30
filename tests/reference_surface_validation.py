"""CATIA integration for image-inspired panels. Never a Class-A acceptance test."""
import argparse
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
from controller import Controller,save_json
from surfaces import CATALOG,review_sources
from agent import Agent
from providers import PROVIDERS
from surface_quality import load_step,facts
from surface_validation import negative_controls


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def simulated_gpt(controller):
    requests=[];reviews=[];transcript=[]
    class Response(BytesIO):headers={'Content-Type':'text/event-stream'}
    def transport(request,provider):
        assert provider==PROVIDERS[2] and request.full_url=='https://api.openai.com/v1/chat/completions'
        payload=json.loads(request.data);requests.append(payload)
        spec=next(t['function'] for t in payload['tools'] if t['function']['name']=='build_surface')
        assert 'fender_reference' in spec['parameters']['properties']['template']['enum']
        if len(requests)==1:
            chunks=[{'tool_calls':[{'index':0,'id':'fender-ref','function':{'name':'build_surface','arguments':'{"template":"fender_'}}]},
                    {'tool_calls':[{'index':0,'function':{'arguments':'reference"}'}}]}]
        else:
            assert any(m['role']=='tool' for m in payload['messages'])
            chunks=[{'content':'参考图翼子板演示已创建，含轮拱、侧面开口和工程折边；尚未通过A级曲面验收。'}]
        raw=''.join('data: '+json.dumps({'choices':[{'delta':c}]})+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        return Response(raw.encode())
    def approve(name,args):
        assert name=='build_surface' and args['all_parameters_mm']['WheelRadius']==420
        assert 'StyleSurfaceBuild' in args['native_builder_source'] and 'fender_reference' in args['generator_source']
        reviews.append(name);return True
    agent=Agent(controller,transcript.append,approve,lambda:'')
    with patch('agent.open_request',transport):
        agent.send('创建参考图样式翼子板演示，先审阅参数和程序。','https://api.openai.com/v1','test-placeholder','gpt-4.1',{},provider=PROVIDERS[2])
    tools=[json.loads(m['content']) for m in agent.messages if m['role']=='tool']
    assert len(tools)==1 and tools[0]['ok'] and len(requests)==2 and len(reviews)==1
    return {'ok':True,'real_gpt_tested':False,'network_requests':0,'protocol':'deterministic in-process SSE interception; real CATIA build',
            'transcript':''.join(transcript),'result':tools[0]['result']}


def native_checks(result,app,roundtrip=False):
    path=Path(result['native']['catpart'])
    docs=[app.Documents.Item(i) for i in range(1,app.Documents.Count+1)]
    doc=next((d for d in docs if str(d.FullName).lower()==str(path).lower()),None)
    if doc is None:doc=app.Documents.Open(str(path))
    doc.Activate();p=doc.Part;v=result['parameters'];body=p.HybridBodies.Item('V2_SurfaceDemo');construction=p.HybridBodies.Item('V2_Construction')
    assert doc.Saved
    for key,value in v.items():assert abs(p.Parameters.Item(key).Value-value)<1e-6,key
    assert abs(body.HybridShapes.Item('ReturnFlange').EndOffset.Value-v['FlangeDepth'])<1e-6
    assert abs(body.HybridShapes.Item('Offset').OffsetValue.Value-v['OffsetDistance'])<1e-6
    if result['template']=='fender_reference':
        pt=construction.HybridShapes.Item('Outline_P0')
        assert abs(pt.X.Value+v['WheelRadius'])<1e-6 and abs(pt.Z.Value-v['WheelCenterZ'])<1e-6
        marker=construction.HybridShapes.Item('MarkerEllipse_P0')
        assert abs(marker.X.Value-v['MarkerX']-v['MarkerWidth']/2)<1e-6
        assert abs(marker.Z.Value-v['MarkerZ'])<1e-6
    else:
        pt=construction.HybridShapes.Item('Outline_P0')
        assert abs(pt.X.Value-.5*v['RoofLength']-.2256*v['EdgeBow'])<1e-6
        assert abs(pt.Y.Value-.44*(v['RoofWidth']-v['RearTaper']))<1e-6
        center=construction.HybridShapes.Item('Section_3_P4')
        assert abs(center.Z.Value-v['LongCrown']-v['CrossCrown'])<1e-6
    q=result['quality']
    assert q['operations_passed'] and q['seam']['sampled_g2'] and q['reference_features']['passed']
    assert not result['class_a_accepted'] and p.Relations.Count>200
    info={'ok':True,'native_relations':p.Relations.Count,'named_parameters_verified':len(v),'native_history':True}
    if roundtrip:
        native_area=doc.GetWorkbench('SPAWorkbench').GetMeasurable(p.CreateReferenceFromObject(body.HybridShapes.Item('FinalPanel'))).Area
        before=digest(path);doc.Close();doc=app.Documents.Open(str(path));p=doc.Part;body=p.HybridBodies.Item('V2_SurfaceDemo')
        assert doc.Saved and digest(path)==before
        for key,value in v.items():assert abs(p.Parameters.Item(key).Value-value)<1e-6
        reopened_area=doc.GetWorkbench('SPAWorkbench').GetMeasurable(p.CreateReferenceFromObject(body.HybridShapes.Item('FinalPanel'))).Area
        assert abs(reopened_area-native_area)*1e6<.01
        step=path.parent/'reopened-panel.step';assert not step.exists();doc.ExportData(str(step),'stp')
        exported=facts(load_step(step));reference=q['geometry']['FinalPanel']
        assert exported['valid'] and exported['solid_count']==0 and exported['face_count']==reference['face_count']
        assert abs(exported['area_mm2']-reference['area_mm2'])<max(.2,reference['area_mm2']*1e-6)
        info.update(saved_reopened=True,original_disk_unchanged=True,reexported_step=exported)
    return info


def historical_checks(controller,report,app):
    original=report['checks']['gpt-simulation-fender-create']['result']
    latest=report['checks']['fender_reference-parameter-rollback']['result']
    path=latest['native']['catpart']
    doc=next(app.Documents.Item(i) for i in range(1,app.Documents.Count+1) if str(app.Documents.Item(i).FullName).lower()==path.lower())
    oldhash=digest(path)
    roofpath=report['checks']['roof_reference-parameter-rollback']['result']['native']['catpart']
    doc.Part.Parameters.Item('FlangeDepth').Value=19
    doc.Part.Update();assert not doc.Saved
    try:
        controller.build_surface('fender_reference',{'FlangeDepth':20},original['manifest'],review_sources(ROOT)[0])
        raise AssertionError('unsaved sibling was overwritten')
    except RuntimeError as exc:
        assert 'related CATPart has unsaved edits' in str(exc),str(exc)
    assert digest(path)==oldhash and not doc.Saved
    # Discard only the deliberate unsaved mutation in our own test document.
    doc.Close();doc=app.Documents.Open(path);assert doc.Saved and digest(path)==oldhash
    revised=controller.build_surface('fender_reference',{'FlangeDepth':20},original['manifest'],review_sources(ROOT)[0])
    assert digest(path)==oldhash and Path(original['native']['catpart']).is_file()
    openpaths=[str(app.Documents.Item(i).FullName).lower() for i in range(1,app.Documents.Count+1)]
    assert path.lower() not in openpaths and roofpath.lower() in openpaths
    assert revised['parameters']['FlangeDepth']==20
    return {'ok':True,'unsaved_sibling_blocked':True,'saved_sibling_session_switched':True,
            'unrelated_roof_stayed_open':True,'old_file_preserved':True,'result':revised,
            'native_check':native_checks(revised,app,True)}


def main():
    import pythoncom,win32com.client
    pythoncom.CoInitialize();parser=argparse.ArgumentParser();parser.add_argument('--workspace',required=True,type=Path);args=parser.parse_args()
    args.workspace.mkdir(parents=True,exist_ok=False);controller=Controller(args.workspace)
    app=win32com.client.GetActiveObject('CATIA.Application')
    report={'version':'0.4.0','class_a_accepted':False,'real_gpt_tested':False,'checks':{}}
    def record(name,value):
        report['checks'][name]=value;save_json(args.workspace/'validation.json',report);print('PASS',name,flush=True)
    before=controller.info()['path']
    for template,values in [('fender_reference',{'WheelRadius':800}),('roof_reference',{'EdgeBow':500}),
                            ('fender_reference',{'MarkerZ':10}),('roof_reference',{'RoofWidth':float('nan')}),
                            ('fender_reference',{'MarkerWidth':True}),('roof_reference',{'unknown':1})]:
        try:controller.build_surface(template,values);raise AssertionError('invalid value accepted')
        except ValueError:pass
    try:controller.build_surface('fender_reference',expected_sha256='stale');raise AssertionError('stale review accepted')
    except ValueError:pass
    denied=Agent(controller,lambda _:None,lambda *_:False,lambda:'')
    assert not denied.execute('build_surface',{'template':'fender_reference'})['ok']
    assert controller.info()['path']==before and not list((args.workspace/'surfaces').glob('*'))
    record('pre-mutation-rejections',{'ok':True,'invalid_parameters':6,'stale_source_review':True,'approval_denied':True})
    record('continuity-negative-controls',negative_controls())
    simulated=simulated_gpt(controller);fender=simulated['result'];simulated['native_check']=native_checks(fender,app)
    record('gpt-simulation-fender-create',simulated)
    roof=controller.build_surface('roof_reference',expected_sha256=review_sources(ROOT)[0])
    record('roof-create',{'ok':True,'result':roof,'native_check':native_checks(roof,app)})
    edits={'fender_reference':{'FenderLength':1580,'FenderHeight':1040,'WheelRadius':445,'WheelCenterZ':110,'Bulge':100,
                             'ShoulderRise':40,'MarkerX':360,'MarkerZ':780,'MarkerWidth':100,'MarkerHeight':42,'FlangeDepth':24,'OffsetDistance':1.6},
           'roof_reference':{'RoofLength':1650,'RoofWidth':1450,'LongCrown':95,'CrossCrown':65,'RearTaper':110,'EdgeBow':45,'FlangeDepth':28,'OffsetDistance':1.8}}
    for template,original in [('fender_reference',fender),('roof_reference',roof)]:
        before=digest(original['native']['catpart'])
        edited=controller.build_surface(template,edits[template],original['manifest'],review_sources(ROOT)[0])
        assert digest(original['native']['catpart'])==before
        assert abs(edited['quality']['geometry']['Joined']['area_mm2']-original['quality']['geometry']['Joined']['area_mm2'])>100
        check=native_checks(edited,app,True)
        record(template+'-edit-reopen-step',{'ok':True,'original_disk_unchanged':True,'native_check':check,'result':edited})
        editedhash=digest(edited['native']['catpart'])
        rollback=controller.build_surface(template,original['parameters'],edited['manifest'],review_sources(ROOT)[0])
        assert digest(edited['native']['catpart'])==editedhash
        delta=abs(rollback['quality']['geometry']['Joined']['area_mm2']-original['quality']['geometry']['Joined']['area_mm2'])
        assert delta<.1,delta
        record(template+'-parameter-rollback',{'ok':True,'previous_disk_unchanged':True,'area_recovery_error_mm2':delta,
                                              'native_check':native_checks(rollback,app),'result':rollback})
    record('historical-revision-switch-and-unsaved-guard',historical_checks(controller,report,app))
    record('snapshot-native-gsd',{'ok':bool(controller.info()['hybrid_bodies'])})
    report['ok']=True;save_json(args.workspace/'validation.json',report)


if __name__=='__main__':main()
