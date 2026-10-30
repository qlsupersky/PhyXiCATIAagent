"""Bounded axis-aligned planar annular groove editing on imported solid BREP.

OCCT booleans preserve the customer's solid. No authored history is inferred.
Only closed nested planar loops are supported; every edit produces a new STEP.
"""
from pathlib import Path
import json,hashlib,math
import numpy as np
from surface_quality import load_step,facts,faces,entities

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def mass(shape,volume=False):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    p=GProp_GProps()
    if volume:BRepGProp.VolumeProperties_s(shape,p,1e-8)
    else:BRepGProp.SurfaceProperties_s(shape,p,1e-8)
    return abs(p.Mass())

def face_of(wire):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    return BRepBuilderAPI_MakeFace(wire,True).Face()

def loops(face):
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopoDS import TopoDS
    return sorted([(mass(face_of(TopoDS.Wire_s(w))),TopoDS.Wire_s(w)) for w in entities(face,TopAbs_WIRE)],key=lambda x:x[0],reverse=True)

def boolean(a,b,mode):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut,BRepAlgoAPI_Fuse,BRepAlgoAPI_Common
    op={'cut':BRepAlgoAPI_Cut,'fuse':BRepAlgoAPI_Fuse,'common':BRepAlgoAPI_Common}[mode](a,b)
    op.Build()
    if not op.IsDone():raise ValueError('OCCT boolean failed')
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    unify=ShapeUpgrade_UnifySameDomain(op.Shape(),True,True,False);unify.Build()
    return unify.Shape()

def planes(shape,axis):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    result=[]
    for i,f in enumerate(faces(shape)):
        surf=BRepAdaptor_Surface(f)
        if surf.GetType()!=GeomAbs_Plane:continue
        plane=surf.Plane();n=plane.Axis().Direction().Coord()
        if abs(n[axis])<1-1e-9:continue
        ll=loops(f)
        result.append(dict(face_id=f'face:{i}',coordinate_mm=plane.Location().Coord()[axis],
                           area_mm2=mass(f),loop_areas_mm2=[v[0] for v in ll],face=f,loops=ll))
    return result

def inventory(step,axis='Y'):
    shape=load_step(step);idx='XYZ'.index(axis);basic=facts(shape)
    rings=[]
    for p in planes(shape,idx):
        big=[v for v in p['loop_areas_mm2'] if v>500]
        if len(big)>=2 and p['area_mm2']<.95*big[0]:
            rings.append({k:v for k,v in p.items() if k not in ('face','loops')})
    return dict(source_step=str(step),source_sha256=digest(step),facts=basic,volume_mm3=mass(shape,True),axis=axis,
                cylindrical_bore_candidates=bore_candidates(shape),
                annular_planar_candidates=rings,
                limits=['环形面是几何候选，不能仅凭面数认定为槽；须核对深度、上下材料与图片。',
                        'STEP不保留原SW槽、螺纹孔特征或设计意图；本工具不自动给出全部孔洞数。'])

def bore_candidates(shape):
    """Conservative inward cylindrical groups; NOT all holes or thread recovery."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_REVERSED,TopAbs_SOLID,TopAbs_IN
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    solids=entities(shape,TopAbs_SOLID)
    if len(solids)!=1:return []
    solid=TopoDS.Solid_s(solids[0]);groups={}
    for i,f in enumerate(faces(shape)):
        a=BRepAdaptor_Surface(f)
        if a.GetType()!=GeomAbs_Cylinder or f.Orientation()!=TopAbs_REVERSED:continue
        c=a.Cylinder();d=np.asarray(c.Axis().Direction().Coord());o=np.asarray(c.Location().Coord())
        for v in d:
            if abs(v)>1e-8:
                if v<0:d=-d
                break
        foot=o-d*np.dot(o,d);r=c.Radius()
        key=tuple(round(float(v),5) for v in [*foot,*d,r])
        bounds=np.asarray(facts(f)['bounds_mm']).reshape(2,3)
        # Finite face bounds supply conservative axial ranges.
        corners=np.asarray([[x,y,z] for x in bounds[:,0] for y in bounds[:,1] for z in bounds[:,2]])
        extent=corners@d
        g=groups.setdefault(key,dict(axis_direction=d.tolist(),axis_point_mm=foot.tolist(),radius_mm=r,faces=[],area_mm2=0.,lo=float('inf'),hi=-float('inf')))
        g['faces'].append(f'face:{i}');g['area_mm2']+=mass(f);g['lo']=min(g['lo'],float(extent.min()));g['hi']=max(g['hi'],float(extent.max()))
    rows=[]
    for g in groups.values():
        length=g['hi']-g['lo'];coverage=g['area_mm2']/(2*math.pi*g['radius_mm']*length) if length>1e-7 else 0
        if not .98<=coverage<=1.02:continue
        d=np.asarray(g['axis_direction']);o=np.asarray(g['axis_point_mm'])
        ends=[o+d*(g['lo']-.05),o+d*(g['hi']+.05)]
        material=[BRepClass3d_SolidClassifier(solid,gp_Pnt(*p),1e-7).State()==TopAbs_IN for p in ends]
        rows.append({**g,'diameter_mm':2*g['radius_mm'],'axial_span_mm':length,'full_cylinder_area_ratio':coverage,
                     'axial_end_material_samples':material,'interpretation':'blind_candidate' if any(material) else 'open_both_ends_candidate'})
    return rows

def translated(shape,axis,distance):
    from OCP.gp import gp_Trsf,gp_Vec
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    xyz=[0.,0.,0.];xyz[axis]=distance;t=gp_Trsf();t.SetTranslation(gp_Vec(*xyz))
    return BRepBuilderAPI_Transform(shape,t,True).Shape()

def prism(face,axis,depth):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    xyz=[0.,0.,0.];xyz[axis]=depth
    return BRepPrimAPI_MakePrism(face,gp_Vec(*xyz)).Shape()

def exchange_ready_tool(tool):
    """Convert generated offset/extrusion geometry to STEP-supported NURBS.

    Imported offset curves can be valid in memory yet be omitted by the STEP
    writer. Keep original tolerances; reject changes in volume or bounds.
    """
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    from OCP.BRepAdaptor import BRepAdaptor_Curve,BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.GeomAbs import GeomAbs_OtherCurve,GeomAbs_Plane,GeomAbs_Cylinder,GeomAbs_Cone,GeomAbs_Sphere,GeomAbs_Torus
    before=facts(tool);v0=mass(tool,True)
    unsupported=any(BRepAdaptor_Curve(TopoDS.Edge_s(e)).GetType()==GeomAbs_OtherCurve for e in entities(tool,TopAbs_EDGE))
    analytic=(GeomAbs_Plane,GeomAbs_Cylinder,GeomAbs_Cone,GeomAbs_Sphere,GeomAbs_Torus)
    unsupported=unsupported or any(BRepAdaptor_Surface(f).GetType() not in analytic for f in faces(tool))
    if before['valid'] and before['solid_count']==1 and not unsupported:
        return tool,dict(method='Original valid STEP-supported tool; no conversion',before=before,after=before,volume_before_mm3=v0,volume_after_mm3=v0,bounds_error_mm=0.)
    fix=ShapeFix_Shape(tool);fix.Perform()
    fixed=fix.Shape()
    if not facts(fixed)['valid']:raise ValueError('槽工具体拓扑整理后无效')
    ready=BRepBuilderAPI_NurbsConvert(fixed,True).Shape()
    after=facts(ready);v1=mass(ready,True)
    bounds_error=max(abs(a-b) for a,b in zip(before['bounds_mm'],after['bounds_mm']))
    if not after['valid'] or after['solid_count']!=1 or abs(v1-v0)>max(.01,v0*1e-6) or bounds_error>1e-4:
        raise ValueError('槽工具STEP表示转换改变几何，拒绝执行')
    return ready,dict(method='ShapeFix(default tolerances) + NURBS representation for STEP',before=before,after=after,volume_before_mm3=v0,volume_after_mm3=v1,bounds_error_mm=bounds_error)

def offset_loop(wire,amount):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_WIRE
    base=mass(face_of(wire));candidates=[]
    for sign in [-1,1]:
        op=BRepOffsetAPI_MakeOffset(wire,GeomAbs_Arc,False);op.Perform(sign*amount)
        if not op.IsDone():continue
        ww=entities(op.Shape(),TopAbs_WIRE)
        if len(ww)!=1:continue
        w=TopoDS.Wire_s(ww[0]);area=mass(face_of(w))
        if area>base:candidates.append((area,w))
    if len(candidates)!=1:raise ValueError('无法得到唯一向材料外侧偏置的闭合轮廓')
    return candidates[0][1]

def make_plan(step,directory,operation,face_id,axis='Y',rim_coordinate=None,width=3.,depth=4.,center_offset=4.):
    if axis not in 'XYZ' or len(axis)!=1:raise ValueError('axis must be X/Y/Z')
    if operation not in ('remove_existing','add_groove'):raise ValueError('unsupported operation')
    for v in [width,depth,center_offset]:
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=30:raise ValueError('尺寸必须为(0,30]mm有限数')
    idx='XYZ'.index(axis);shape=load_step(step);pp=planes(shape,idx)
    selected=next((p for p in pp if p['face_id']==face_id),None)
    if not selected:raise ValueError('指定面不是所选轴的平面')
    ll=selected['loops'];large=[(a,w) for a,w in ll if a>500]
    if len(large)!=2:raise ValueError('仅支持含两个大型闭合嵌套轮廓的密封环面')
    coordinate=selected['coordinate_mm'];floor=None;tool_normalization=None
    if operation=='remove_existing':
        if rim_coordinate is None or not isinstance(rim_coordinate,(int,float)) or not 0<rim_coordinate-coordinate<=30:
            raise ValueError('删除原有槽必须提供高于槽底0–30mm的实际密封面坐标')
        # Pick the two neighboring lip loops that bracket the projected floor.
        lip=[]
        for p in pp:
            if abs(p['coordinate_mm']-rim_coordinate)>1e-6:continue
            for area,w in p['loops']:
                if large[1][0]*.8<area<large[0][0]*1.2:
                    lip.append((area,w))
        # Straight-wall grooves have equal top/bottom loop areas; drafted ones
        # bracket them strictly. Keep a small numeric matching allowance.
        inside=[v for v in lip if v[0]<=large[1][0]+max(.01,large[1][0]*1e-6)]
        outside=[v for v in lip if v[0]>=large[0][0]-max(.01,large[0][0]*1e-6)]
        if not inside or not outside:raise ValueError('未找到包围整个槽底的两个密封面槽口边界')
        inner=max(inside,key=lambda x:x[0]);outer=min(outside,key=lambda x:x[0])
        ring=boolean(face_of(outer[1]),face_of(inner[1]),'cut')
        tool=prism(ring,idx,-(rim_coordinate-coordinate+.001))
        floor=coordinate;coordinate=rim_coordinate
        result=boolean(shape,tool,'fuse')
    else:
        if center_offset<=width/2:raise ValueError('槽中心距内壁必须大于槽宽一半')
        inner=offset_loop(large[1][1],center_offset-width/2)
        outer=offset_loop(large[1][1],center_offset+width/2)
        ring=boolean(face_of(outer),face_of(inner),'cut')
        ring_area=mass(ring);supported=mass(boolean(ring,selected['face'],'common'))
        if abs(supported-ring_area)>max(.01,ring_area*1e-6):
            raise ValueError(f'整槽超出指定密封面的材料范围：有效支承面积{supported:.3f}/{ring_area:.3f} mm²；请扩大裙边或调整参数，不自动替换尺寸')
        # Verify full depth at 3 levels to reject breakthrough before cutting.
        for t in [.01,.5,1.0]:
            probe=prism(translated(ring,idx,-depth*t),idx,-.001)
            if mass(boolean(probe,shape,'common'),True)<mass(probe,True)*.999:
                raise ValueError('整槽深度穿透材料或与已有孔/空腔相交，拒绝执行')
        # A flush top also keeps NURBS cutter surface bounds within the part.
        # A former +.001 overrun appeared in CGM's exported trimmed-surface
        # envelope, so it correctly failed the unchanged 1e-4 envelope gate.
        tool=prism(ring,idx,-depth);floor=coordinate-depth
        tool,tool_normalization=exchange_ready_tool(tool)
        result=boolean(shape,tool,'cut')
    before=facts(shape);after=facts(result);v0=mass(shape,True);v1=mass(result,True)
    if not after['valid'] or after['solid_count']!=1:raise ValueError('修改后非有效单实体')
    if max(abs(a-b) for a,b in zip(before['bounds_mm'],after['bounds_mm']))>1e-4:raise ValueError('修改改变外包络，拒绝导入')
    if (operation=='remove_existing' and v1<=v0+.01) or (operation=='add_groove' and v1>=v0-.01):raise ValueError('没有预期材料变化')
    # Independent directional differences: no removed material on fill, none added on cut.
    unexpected=mass(boolean(shape,result,'cut') if operation=='remove_existing' else boolean(result,shape,'cut'),True)
    if unexpected>max(.01,v0*1e-8):raise ValueError('存在非预期方向的材料变化')
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    # Reconstructed STEP p-curves can become inconsistent on translated
    # trimmed BSpline faces. Export the 3D curves and let the reader rebuild
    # their surface representations, at explicit micron precision. Retain
    # the same validity/solid/volume gates; never heal by loosening them.
    from OCP.Interface import Interface_Static
    target=out/'candidate.step';writer=STEPControl_Writer()
    old_mode=Interface_Static.IVal_s('write.surfacecurve.mode')
    old_precision_mode=Interface_Static.IVal_s('write.precision.mode')
    old_precision=Interface_Static.RVal_s('write.precision.val')
    try:
        Interface_Static.SetIVal_s('write.surfacecurve.mode',0)
        Interface_Static.SetIVal_s('write.precision.mode',1)
        Interface_Static.SetRVal_s('write.precision.val',1e-6)
        if writer.Transfer(result,STEPControl_AsIs)!=IFSelect_RetDone:raise ValueError('STEP转换失败')
        if writer.Write(str(target))!=IFSelect_RetDone:raise ValueError('STEP写入失败')
    finally:
        Interface_Static.SetIVal_s('write.surfacecurve.mode',old_mode)
        Interface_Static.SetIVal_s('write.precision.mode',old_precision_mode)
        Interface_Static.SetRVal_s('write.precision.val',old_precision)
    reloaded=load_step(target);check=facts(reloaded)
    step_ok=check['valid'] and check['solid_count']==1 and abs(mass(reloaded,True)-v1)<=max(.01,v1*1e-6)
    # The full candidate STEP is diagnostic only: application imports just
    # the groove operand and preserves the native customer body. Validate
    # the predicted full solid with lossless BREP, even when its trimmed
    # surfaces cannot survive an additional STEP roundtrip.
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape
    brep_target=out/'candidate.brep'
    if not BinTools.Write_s(result,str(brep_target)):raise ValueError('BREP预演写出失败')
    exact=TopoDS_Shape()
    if not BinTools.Read_s(exact,str(brep_target)):raise ValueError('BREP预演重读失败')
    exact_check=facts(exact)
    if not exact_check['valid'] or exact_check['solid_count']!=1 or abs(mass(exact,True)-v1)>max(.01,v1*1e-6):raise ValueError('BREP预演不是有效单实体或体积改变')
    tool_target=out/'groove-tool.step';tool_writer=STEPControl_Writer()
    try:
        Interface_Static.SetIVal_s('write.surfacecurve.mode',0)
        Interface_Static.SetIVal_s('write.precision.mode',1)
        Interface_Static.SetRVal_s('write.precision.val',1e-6)
        if tool_writer.Transfer(tool,STEPControl_AsIs)!=IFSelect_RetDone or tool_writer.Write(str(tool_target))!=IFSelect_RetDone:raise ValueError('槽工具实体STEP写出失败')
    finally:
        Interface_Static.SetIVal_s('write.surfacecurve.mode',old_mode)
        Interface_Static.SetIVal_s('write.precision.mode',old_precision_mode)
        Interface_Static.SetRVal_s('write.precision.val',old_precision)
    tool_reload=load_step(tool_target);tool_check=facts(tool_reload)
    if not tool_check['valid'] or tool_check['solid_count']!=1 or abs(mass(tool_reload,True)-mass(tool,True))>max(.01,mass(tool,True)*1e-6):raise ValueError('槽工具实体重读校验失败')
    info=dict(operation=operation,source_step=str(step),source_sha256=digest(step),candidate_step=str(target),candidate_sha256=digest(target),
              candidate_brep=str(brep_target),candidate_brep_sha256=digest(brep_target),candidate_brep_facts=exact_check,candidate_step_roundtrip_ok=step_ok,candidate_step_role='Diagnostic only; never imported. Validated full candidate is exact BREP. Native CATIA applies only groove-tool.step.',tool_step=str(tool_target),tool_sha256=digest(tool_target),tool_facts=tool_check,face_id=face_id,axis=axis,rim_coordinate_mm=coordinate,floor_coordinate_mm=floor,parameters=dict(width_mm=width,depth_mm=depth,center_offset_mm=center_offset) if operation=='add_groove' else {},
              before=before,after=after,tool_normalization=tool_normalization,step_reload_facts=check,step_reload_volume_mm3=mass(reloaded,True),step_export=dict(surfacecurve_mode=0,precision_mm=1e-6),volume_before_mm3=v0,volume_after_mm3=v1,volume_delta_mm3=v1-v0,unexpected_direction_volume_mm3=unexpected,
              implementation='OCCT完整环带预演；正式应用导入槽工具实体并在CATIA副本上原生Boolean Add/Remove；不恢复原SW/Pocket历史',
              limits=['新增为直壁平底闭合槽，未实现1.5°拔模、R0.5圆角或螺柱。','删除仅限已识别的平面闭合槽口至槽底环带；不支持任意自由曲面槽。','不构成密封、粗糙度、公差或制造验收。'])
    (out/'geometry-plan.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    return info
