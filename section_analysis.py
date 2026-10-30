"""Read-only trimmed BREP sections and direction-defined differential diagnostics."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from pathlib import Path
import numpy as np

LABELS = {
    'convex_toward_reference': ('凸向参考方向', '#d95f02'),
    'concave_toward_reference': ('凹向参考方向', '#1976b9'),
    'saddle': ('鞍形 / 双向异号', '#9854b5'),
    'flat': ('近似平面', '#777777'),
    'normal_transverse': ('法向近垂直参考方向', '#aaaaaa'),
}


def classify_curvature(k1, k2, tolerance=1e-6):
    """D2.n convention: negative normal curvature is convex toward n."""
    if k1*k2 < -tolerance*tolerance and min(abs(k1),abs(k2)) > tolerance:
        return 'saddle'
    if max(abs(k1),abs(k2)) <= tolerance:
        return 'flat'
    if max(k1,k2) <= tolerance and min(k1,k2) < -tolerance:
        return 'convex_toward_reference'
    return 'concave_toward_reference'


def sample_curvature(shape, reference, grid=15):
    from surface_quality import faces
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt,gp_Pnt2d,gp_Vec
    rows=[]; errors=[]; excluded=0
    direction=np.asarray(reference,dtype=float);direction/=np.linalg.norm(direction)
    for fi,face in enumerate(faces(shape)):
        surface=BRep_Tool.Surface_s(face)
        ua,ub,va,vb=BRepTools.UVBounds_s(face)
        if not np.isfinite([ua,ub,va,vb]).all():
            errors.append({'face_id':f'face:{fi}','error':'unbounded_uv'});continue
        for u in np.linspace(ua,ub,grid+2)[1:-1]:
            for v in np.linspace(va,vb,grid+2)[1:-1]:
                if BRepClass_FaceClassifier(face,gp_Pnt2d(float(u),float(v)),1e-7).State()!=TopAbs_IN:
                    excluded+=1;continue
                try:
                    p=gp_Pnt();du,dv,duu,dvv,duv=[gp_Vec() for _ in range(5)]
                    surface.D2(float(u),float(v),p,du,dv,duu,dvv,duv)
                    vec=lambda x:np.asarray(x.Coord(),dtype=float)
                    jac=np.column_stack([vec(du),vec(dv)]);n=np.cross(jac[:,0],jac[:,1])
                    n/=np.linalg.norm(n);dot=float(n@direction)
                    if dot<0:n=-n
                    metric=jac.T@jac
                    second=np.array([[n@vec(duu),n@vec(duv)],[n@vec(duv),n@vec(dvv)]])
                    ks=np.sort(np.linalg.eigvals(np.linalg.solve(metric,second)).real)
                    if not np.isfinite(ks).all():raise ValueError('non-finite curvature')
                    label=classify_curvature(*ks) if abs(dot)>=.15 else 'normal_transverse'
                    rows.append({'face_id':f'face:{fi}','point_mm':list(p.Coord()),'normal':n.tolist(),
                                 'k_per_mm':ks.tolist(),'class':label,'reference_alignment':abs(dot)})
                except Exception as exc:
                    errors.append({'face_id':f'face:{fi}','uv':[float(u),float(v)],'error_type':type(exc).__name__})
    return {'reference_direction':direction.tolist(),'grid_per_face':[grid,grid],
            'count_by_class':dict(Counter(r['class'] for r in rows)),
            'sample_count':len(rows),'excluded_trim_samples':excluded,'errors':errors,'samples':rows,
            'convention':'Normal chosen toward reference. k=D2 dot normal / first fundamental form. Negative=convex toward that normal; positive=concave; opposite signs=saddle.',
            'tolerance_per_mm':1e-6,'coverage':'Finite uniform UV samples inside trimmed faces, NOT area percentages or global extrema. Face IDs belong only to this STEP hash.'}


def section_bending(section, axis):
    """Bounded finite-difference evidence for z(horizontal) on monotone edge spans."""
    if axis not in (0,1):return {'available':False,'reason':'Horizontal XY section has no Z-height bending'}
    horizontal=1 if axis==0 else 0
    counts=Counter();examples=[];inflections=[];skipped=0
    for edge in section['edges']:
        pts=np.asarray(edge.get('samples_3d',[]),dtype=float)
        if len(pts)<9:skipped+=1;continue
        dx=np.diff(pts[:,horizontal])
        if np.all(dx<0):pts=pts[::-1];dx=-dx[::-1]
        if not np.all(dx>1e-8):skipped+=1;continue
        x,z=pts[:,horizontal],pts[:,2]
        dz=np.gradient(z,x);curvature=np.gradient(dz,x)/(1+dz*dz)**1.5
        for i in range(3,len(pts)-3):
            k=float(curvature[i]);label='convex_toward_+Z' if k<-1e-6 else 'concave_toward_+Z' if k>1e-6 else 'near_zero'
            counts[label]+=1
            if not any(e['class']==label for e in examples):examples.append({'point_mm':pts[i].tolist(),'curvature_per_mm':k,'class':label})
            if i>3 and curvature[i-1]*k<0 and max(abs(curvature[i-1]),abs(k))>1e-6:
                inflections.append({'edge_index':edge['index'],'bracket_mm':[pts[i-1].tolist(),pts[i].tolist()]})
    return {'available':True,'horizontal_axis':'XYZ'[horizontal],'reference':'+Z','count_by_class':dict(counts),
            'examples':examples,'inflection_brackets':inflections[:12],'skipped_nonmonotone_edges':skipped,
            'method':'Finite difference of 81 edge samples; endpoints excluded, no derivatives across seams or gaps. Inflections are brackets, not exact coordinates.'}


def analyze(step, directory, reference_axis='Z', fractions=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from simplecadapi.inspect import brep
    from surface_quality import load_step,facts,entities
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    if reference_axis not in ('X','Y','Z'):raise ValueError('reference_axis must be X/Y/Z')
    fractions=[.2,.5,.8] if fractions is None else fractions
    if not isinstance(fractions,list) or not 1<=len(fractions)<=5 or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not 0<t<1 for t in fractions):
        raise ValueError('fractions must contain 1-5 numbers strictly inside (0,1)')
    path=Path(step).resolve();out=Path(directory).resolve();out.mkdir(parents=True,exist_ok=True)
    shape=load_step(path);basic=facts(shape);bounds=np.array(basic['bounds_mm']).reshape(2,3)
    direction=np.eye(3)['XYZ'.index(reference_axis)]
    grid=5 if basic['face_count']>300 else 9 if basic['face_count']>100 else 15
    curvature=sample_curvature(shape,direction,grid=grid)
    sections=[];failures=[]
    for axis in range(3):
        for f in fractions:
            origin=(bounds[0]+bounds[1])/2;origin[axis]=bounds[0,axis]+f*(bounds[1,axis]-bounds[0,axis])
            try:
                value=brep.inspect_section_rdescriptor(model_or_path=path,origin=origin.tolist(),normal=np.eye(3)[axis].tolist(),
                                                      samples_per_edge=81,connection_tolerance=1e-4,compact=False)
                sections.append({'axis':'XYZ'[axis],'fraction':f,'coordinate_mm':float(origin[axis]),'section':value,'bending':section_bending(value,axis)})
            except Exception as exc:
                failures.append({'axis':'XYZ'[axis],'fraction':f,'error_type':type(exc).__name__,'error':str(exc)})
    plt.rcParams['font.sans-serif']=['Microsoft YaHei'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(3,len(fractions),figsize=(5*len(fractions),10),squeeze=False,dpi=125)
    for axis in range(3):
        dims=[i for i in range(3) if i!=axis]
        for j,f in enumerate(fractions):
            ax=axes[axis,j];r=next((r for r in sections if r['axis']=='XYZ'[axis] and r['fraction']==f),None)
            if r:
                sec=r['section']
                for edge in sec['edges']:
                    pts=np.array(edge.get('samples_3d',[]))
                    if len(pts):ax.plot(pts[:,dims[0]],pts[:,dims[1]],lw=1.7)
                ax.set_title(f"{'XYZ'[axis]} = {r['coordinate_mm']:.2f} mm\n开曲线 {sec['open_contour_count']} / 闭环 {sec['closed_contour_count']}",fontsize=10)
                if not sec['edges']:ax.text(.5,.5,'无交线',transform=ax.transAxes,ha='center')
            else:ax.set_title('截面计算失败')
            ax.set_xlabel('XYZ'[dims[0]]+' / mm');ax.set_ylabel('XYZ'[dims[1]]+' / mm')
            ax.set_aspect('equal',adjustable='box');ax.grid(alpha=.25)
    fig.suptitle('实际 STEP 与切平面相交所得截面 · 坐标等比例 · 断开曲线不自动连线\nXYZ 为零件全局坐标；开放曲面截面不能用于推断壁厚',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(out/'sections.png');plt.close(fig)
    fig,axes=plt.subplots(2,len(fractions),figsize=(5*len(fractions),6),squeeze=False,dpi=125)
    for axis in range(2):
        horizontal=1 if axis==0 else 0
        for j,f in enumerate(fractions):
            ax=axes[axis,j];r=next((r for r in sections if r['axis']=='XYZ'[axis] and r['fraction']==f),None)
            if r:
                for edge in r['section']['edges']:
                    pts=np.asarray(edge.get('samples_3d',[]))
                    if len(pts):ax.plot(pts[:,horizontal],pts[:,2],lw=1.7)
                ax.set_title(f"{'XYZ'[axis]} = {r['coordinate_mm']:.2f} mm",fontsize=11)
            ax.set_xlabel('XYZ'[horizontal]+' / mm');ax.set_ylabel('Z / mm');ax.grid(alpha=.25)
    fig.suptitle('截面起伏放大观察图 · 各图横纵轴独立缩放（非等比例）\n形状与精确尺寸请结合等比例截面图及几何数据，断口不连线',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.9]);fig.savefig(out/'sections-detail.png');plt.close(fig)
    fig=plt.figure(figsize=(13,9),dpi=125);ax=fig.add_subplot(221,projection='3d')
    projections=[(fig.add_subplot(222),(0,1),'XY · 从 +Z 侧观察'),
                 (fig.add_subplot(223),(0,2),'XZ · 从 +Y 侧观察'),
                 (fig.add_subplot(224),(1,2),'YZ · 从 +X 侧观察')]
    for raw in entities(shape,TopAbs_EDGE):
        curve=BRepAdaptor_Curve(TopoDS.Edge_s(raw));a,b=curve.FirstParameter(),curve.LastParameter()
        points=np.array([curve.Value(float(t)).Coord() for t in np.linspace(a,b,65)])
        ax.plot(*points.T,color='#4b647b',lw=.7)
        for pane,dims,title in projections:pane.plot(points[:,dims[0]],points[:,dims[1]],color='#4b647b',lw=.8)
    ax.set(xlabel='X / mm',ylabel='Y / mm',zlabel='Z / mm');ax.set_box_aspect(np.maximum(bounds[1]-bounds[0],1e-3));ax.view_init(25,-58)
    ax.set_title('三维边界与面片接缝（非实体着色图）')
    ax.zaxis.set_major_locator(plt.MaxNLocator(3))
    for pane,dims,title in projections:
        pane.set(xlabel='XYZ'[dims[0]]+' / mm',ylabel='XYZ'[dims[1]]+' / mm',title=title)
        pane.set_aspect('equal');pane.grid(alpha=.2)
    fig.suptitle('真实边界和面片接缝投影 · 不可将接缝当作孔边',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.95]);fig.savefig(out/'geometry-overview.png');plt.close(fig)
    fig=plt.figure(figsize=(12,8),dpi=125);ax=fig.add_subplot(111,projection='3d')
    for key,(label,color) in LABELS.items():
        pts=np.array([r['point_mm'] for r in curvature['samples'] if r['class']==key])
        if len(pts):ax.scatter(*pts.T,c=color,s=7,label=f'{label} ({len(pts)} 点)')
    ax.set(xlabel='X / mm',ylabel='Y / mm',zlabel='Z / mm');ax.set_box_aspect(np.maximum(bounds[1]-bounds[0],1e-3));ax.view_init(25,-58)
    ax.legend(loc='upper left',fontsize=9);ax.set_title(f'局部主曲率分类 · 法向朝向 +{reference_axis}\n有限 UV 采样点，非面积占比；翻转法向后凹凸互换，鞍形不变')
    ax.zaxis.set_major_locator(plt.MaxNLocator(3))
    fig.tight_layout();fig.savefig(out/'curvature-map.png');plt.close(fig)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'section-evidence.json').write_text(json.dumps({'source_step':str(path),'sha256':digest,'sections':sections,'failures':failures,'curvature':curvature},ensure_ascii=False,indent=2),encoding='utf-8')
    examples={key:[r for r in curvature['samples'] if r['class']==key][::max(1,sum(r['class']==key for r in curvature['samples'])//3)][:3] for key in LABELS}
    report={'version':'0.5.1','source_step':str(path),'source_sha256':digest,'facts':basic,
            'reference_direction':direction.tolist(),'curvature':{k:v for k,v in curvature.items() if k not in ('samples','errors')},
            'curvature_error_count':len(curvature['errors']),'sample_examples':examples,
            'sections':[dict(axis=r['axis'],coordinate_mm=r['coordinate_mm'],edge_count=r['section']['edge_count'],
                             open_contours=r['section']['open_contour_count'],closed_contours=r['section']['closed_contour_count'],bending=r['bending']) for r in sections],
            'section_failures':failures,'images':[str(out/n) for n in ['sections.png','sections-detail.png','geometry-overview.png','curvature-map.png']],
            'evidence':str(out/'section-evidence.json'),'class_a_accepted':False,
            'limits':['开放曲面没有可据此确定的材料内外或壁厚。凹凸必须指明参考法向。',
                      '截面仅覆盖指定位置；采样无法证明全域无拐点、无缺陷或G2连续。',
                      '主曲率是点的双向曲率，不等于X或Y截面的曲率；鞍形在两个主方向凹凸不同。',
                      '截图视觉判断是辅助证据，精确尺寸和拓扑结论必须以几何测量核验。']}
    report['image_sha256']={str(Path(p).name):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in report['images']}
    report['sampling_note']=f'每面{grid}×{grid}有限UV格点；复杂实件降低采样密度，不代表同精度全域检查。'
    (out/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
