"""Independent STEP diagnostics. Finite samples are not Class-A certification."""
import math
from pathlib import Path
import numpy as np


def load_step(path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('无法读取曲面 STEP')
    if reader.TransferRoots() < 1:
        raise ValueError('曲面 STEP 无可转换对象')
    return reader.OneShape()


def entities(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    mapping = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, mapping)
    return [mapping.FindKey(i) for i in range(1, mapping.Extent()+1)]


def faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    return [TopoDS.Face_s(f) for f in entities(shape, TopAbs_FACE)]


def facts(shape):
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_EDGE, TopAbs_SHELL
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    props = GProp_GProps()
    # Adaptive integration avoids partition-dependent area errors on B-splines.
    BRepGProp.SurfaceProperties_s(shape, props, 1e-8, False)
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return {'valid': BRepCheck_Analyzer(shape).IsValid(), 'face_count': len(faces(shape)),
            'shell_count':len(entities(shape,TopAbs_SHELL)),
            'solid_count': len(entities(shape, TopAbs_SOLID)), 'edge_count': len(entities(shape, TopAbs_EDGE)),
            'area_mm2': props.Mass(), 'bounds_mm': list(box.Get())}


def differential(face, point):
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt, gp_Vec
    surface = BRep_Tool.Surface_s(face)
    projection = GeomAPI_ProjectPointOnSurf(point, surface)
    if projection.NbPoints() == 0:
        raise ValueError('连续性采样投影失败')
    u, v = projection.LowerDistanceParameters()
    p, du, dv, duu, dvv, duv = gp_Pnt(), gp_Vec(), gp_Vec(), gp_Vec(), gp_Vec(), gp_Vec()
    surface.D2(u, v, p, du, dv, duu, dvv, duv)
    vec = lambda a: np.array([a.X(), a.Y(), a.Z()])
    jacobian = np.column_stack([vec(du), vec(dv)])
    normal = np.cross(jacobian[:, 0], jacobian[:, 1])
    norm = np.linalg.norm(normal)
    if norm < 1e-10:
        raise ValueError('连续性采样遇到退化法向')
    normal /= norm
    second = np.array([[np.dot(normal, vec(duu)), np.dot(normal, vec(duv))],
                       [np.dot(normal, vec(duv)), np.dot(normal, vec(dvv))]])
    return {'point': vec(p), 'normal': normal, 'jacobian': jacobian, 'second': second,
            'u': u, 'v': v, 'distance': projection.LowerDistance()}


def seam_metrics(left, right):
    """Compare along x=0 seam of this demo; not arbitrary surface matching."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    lf, rf = faces(left), faces(right)
    if not lf or not rf:
        raise ValueError('演示接缝两侧缺少曲面')
    candidates = []
    for raw in entities(left, TopAbs_EDGE):
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(raw))
        a, b = curve.FirstParameter(), curve.LastParameter()
        if all(abs(curve.Value(a+(b-a)*t).X()) < 1e-4 for t in [.1,.5,.9]):
            candidates.append(curve)
    if not candidates or len(candidates)>8:
        raise ValueError('未找到有界的 x=0 演示接缝')
    def nearest(face_list,point):
        vertex=BRepBuilderAPI_MakeVertex(point).Vertex()
        measured=[]
        for face in face_list:
            distance=BRepExtrema_DistShapeShape(vertex,face)
            if not distance.IsDone():raise ValueError('接缝到裁剪面距离计算失败')
            measured.append((distance.Value(),face))
        distance,face=min(measured,key=lambda v:v[0])
        return differential(face,point),distance
    rows = []
    for segment,curve in enumerate(candidates):
      for t in np.linspace(.05, .95, 19):
        pt = curve.Value(curve.FirstParameter()+t*(curve.LastParameter()-curve.FirstParameter()))
        a, da = nearest(lf,pt)
        b, db = nearest(rf,pt)
        dot = float(np.dot(a['normal'], b['normal']))
        sign = 1 if dot >= 0 else -1
        tangent = a['jacobian'][:,0]/np.linalg.norm(a['jacobian'][:,0])
        basis = np.column_stack([tangent, np.cross(a['normal'], tangent)])
        aa = np.linalg.lstsq(a['jacobian'], basis, rcond=None)[0]
        bb = np.linalg.lstsq(b['jacobian'], basis, rcond=None)[0]
        curvature_delta = aa.T@a['second']@aa-sign*(bb.T@b['second']@bb)
        rows.append({'segment':segment,'fraction': float(t), 'gap_mm': float(np.linalg.norm(a['point']-b['point'])),
                     'normal_angle_deg': math.degrees(math.acos(min(1, abs(dot)))),
                     'curvature_tensor_delta_per_mm': float(np.linalg.norm(curvature_delta, ord=2)),
                     'projection_max_mm': max(a['distance'],b['distance'],da,db)})
    gap=max(r['gap_mm'] for r in rows); angle=max(r['normal_angle_deg'] for r in rows)
    curvature=max(r['curvature_tensor_delta_per_mm'] for r in rows)
    g0=gap<=.01 and max(r['projection_max_mm'] for r in rows)<=.01
    g1=g0 and angle<=.1
    return {'samples':rows,'segments':len(candidates), 'max_gap_mm':gap, 'max_normal_angle_deg':angle,
            'max_curvature_tensor_delta_per_mm':curvature, 'sampled_g0':g0,
            'sampled_g1':g1, 'sampled_g2':g1 and curvature<=1e-5,
            'thresholds':{'gap_mm':.01,'angle_deg':.1,'curvature_delta_per_mm':1e-5},
            'scope':'19 finite samples per edge segment along x=0 cut on the SAME loft; segment endpoints and internal guide joins excluded. Tests splitting/rejoining only; no independent Class-A patch matching or global certification.'}


def surface_samples(shape):
    from OCP.BRepTools import BRepTools
    from OCP.BRep import BRep_Tool
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    for face in faces(shape):
        u0,u1,v0,v1 = BRepTools.UVBounds_s(face)
        surface = BRep_Tool.Surface_s(face)
        for u in np.linspace(u0,u1,9)[1:-1]:
            for v in np.linspace(v0,v1,9)[1:-1]:
                if BRepClass_FaceClassifier(face,gp_Pnt2d(float(u),float(v)),1e-7).State() == TopAbs_IN:
                    yield face,surface.Value(float(u),float(v))


def offset_metrics(source, offset, expected):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    values=[]
    for _,pt in surface_samples(source):
        distance=BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(pt).Vertex(),offset)
        if not distance.IsDone():raise ValueError('偏置距离测量失败')
        values.append(distance.Value())
    if not values:raise ValueError('没有可测量的曲面内点')
    deviation=max(abs(v-expected) for v in values)
    return {'samples':len(values),'expected_mm':expected,'min_mm':min(values),'max_mm':max(values),
            'max_deviation_mm':deviation,'passed':deviation<=.02,
            'scope':'Finite interior samples, closest point distance; not a thickness or offset self-intersection certificate.'}


def reference_metrics(shapes, template, parameters):
    """Spatial probes discriminate a real trimmed aperture from an uncut carrier."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    p=parameters
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    depth_edges=[]
    axis=1 if template=='fender_reference' else 2
    for edge in entities(shapes['ReturnFlange'],TopAbs_EDGE):
        c=BRepAdaptor_Curve(TopoDS.Edge_s(edge));a,b=c.FirstParameter(),c.LastParameter()
        coords=lambda t:np.array(c.Value(t).Coord())
        d=coords(b)-coords(a);length=float(np.linalg.norm(d))
        if length>.01 and abs(d[axis])/length>1-1e-8 and np.linalg.norm(coords((a+b)/2)-(coords(a)+coords(b))/2)<.001:
            depth_edges.append(length)
    def ray_distance(name,x,z):
        ray=BRepBuilderAPI_MakeEdge(gp_Pnt(x,-350,z),gp_Pnt(x,350,z)).Edge()
        d=BRepExtrema_DistShapeShape(ray,shapes[name])
        if not d.IsDone():raise ValueError('曲面开口空间检查失败')
        return d.Value()
    skin=facts(shapes['Joined']);flange=facts(shapes['ReturnFlange']);final=facts(shapes['FinalPanel'])
    delta=abs(final['area_mm2']-skin['area_mm2']-flange['area_mm2'])
    result={'flange_depth_mm':p['FlangeDepth'],'final_area_sum_error_mm2':delta,
            'final_single_shell':final['shell_count']==1,
            'measured_flange_depth_edges_mm':depth_edges,
            'flange_depth_verified':bool(depth_edges) and max(abs(v-p['FlangeDepth']) for v in depth_edges)<.01,
            'flange_join_preserved_area':delta<max(.1,final['area_mm2']*1e-6),
            'scope':'Sharp engineering return walls, including aperture walls; deliberately not G2 transitions.'}
    if template=='fender_reference':
        x,z=p['MarkerX'],p['MarkerZ'];w,h=p['MarkerWidth'],p['MarkerHeight']
        center=ray_distance('Joined',x,z)
        before=ray_distance('OutlineTrim',x,z)
        neighbors=[ray_distance('Joined',a,b) for a,b in [(x-.65*w,z),(x+.65*w,z),(x,z-.65*h),(x,z+.65*h)]]
        arch_void=ray_distance('Joined',0,p['WheelCenterZ']+.5*p['WheelRadius'])
        arch_skin=ray_distance('Joined',0,p['WheelCenterZ']+p['WheelRadius']+60)
        result.update(marker_center_clearance_mm=center,marker_carrier_distance_mm=before,
                      marker_neighbor_distances_mm=neighbors,wheel_void_clearance_mm=arch_void,wheel_skin_distance_mm=arch_skin,
                      marker_opening_verified=center>.35*h and before<.01 and max(neighbors)<.01,
                      wheel_opening_verified=arch_void>10 and arch_skin<.01)
    result['passed']=result['final_single_shell'] and result['flange_depth_verified'] and result['flange_join_preserved_area'] and result.get('marker_opening_verified',True) and result.get('wheel_opening_verified',True)
    return result


def analyze(output, expected_offset, template=None, parameters=None):
    output=Path(output)
    shapes={name:load_step(output/(name+'.step')) for name in ['Loft','Trimmed','Left','Right','Joined','Offset']}
    if template in ('roof_reference','fender_reference'):
        for name in ['ReturnFlange','FinalPanel']+(['OutlineTrim'] if template=='fender_reference' else []):
            shapes[name]=load_step(output/(name+'.step'))
    geometry={name:facts(shape) for name,shape in shapes.items()}
    seam=seam_metrics(shapes['Left'],shapes['Right'])
    offset=offset_metrics(shapes['Joined'],shapes['Offset'],expected_offset)
    valid=all(v['valid'] and v['face_count']>0 and v['solid_count']==0 and v['area_mm2']>0 for v in geometry.values())
    trimmed=geometry['Trimmed']['area_mm2']<geometry['Loft']['area_mm2']
    joined=abs(geometry['Joined']['area_mm2']-geometry['Trimmed']['area_mm2'])<max(.05,geometry['Trimmed']['area_mm2']*1e-6)
    reference=reference_metrics(shapes,template,parameters) if template in ('roof_reference','fender_reference') else None
    return {'geometry':geometry,'seam':seam,'offset':offset,'trim_reduced_area':trimmed,'reference_features':reference,
            'join_preserved_area':joined,'operations_passed':valid and trimmed and joined and seam['sampled_g0'] and offset['passed'] and (reference is None or reference['passed']),
            'class_a_accepted':False,'customer_reference_available':False,
            'limitations':['Same-support split seam only','Finite samples, no global G2 proof',
                           'No zebra/highlight acceptance','No customer surface deviation','No manufacturing or vehicle validation']}
