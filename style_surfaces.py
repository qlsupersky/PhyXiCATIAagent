"""Image-inspired native GSD demonstrations. Dimensions are recorded assumptions."""
import math

CATALOG = {
    'roof_reference': {'label':'参考图样式顶盖（外板 / 周边折边）','defaults':{
        'RoofLength':1500,'RoofWidth':1350,'LongCrown':75,'CrossCrown':55,
        'RearTaper':80,'EdgeBow':35,'FlangeDepth':22,'OffsetDistance':1.2}},
    'fender_reference': {'label':'参考图样式翼子板（外轮廓 / 轮拱 / 开口）','defaults':{
        'FenderLength':1500,'FenderHeight':1000,'WheelRadius':420,'WheelCenterZ':100,
        'Bulge':85,'ShoulderRise':30,'MarkerX':380,'MarkerZ':760,
        'MarkerWidth':85,'MarkerHeight':35,'FlangeDepth':18,'OffsetDistance':1.2}}
}


def validate(template,values=None):
    if template not in CATALOG:raise ValueError('未知参考图曲面模板')
    if values is not None and not isinstance(values,dict):raise ValueError('参数须为对象')
    defaults=CATALOG[template]['defaults']
    if set(values or {})-defaults.keys():raise ValueError('存在未知参考图模板参数')
    p={**defaults,**(values or {})}
    for name,value in p.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=5000:
            raise ValueError(name+'须为有限正数（mm）')
    if not .1<=p['OffsetDistance']<=3 or not 5<=p['FlangeDepth']<=40:raise ValueError('偏置限0.1–3mm，折边深度限5–40mm')
    if template=='roof_reference':
        if not 1000<=p['RoofLength']<=2200 or not 1000<=p['RoofWidth']<=1800:raise ValueError('顶盖长度1000–2200、宽1000–1800mm')
        if not 20<=p['LongCrown']<=150 or not 20<=p['CrossCrown']<=120:raise ValueError('顶盖纵向拱高20–150、横向20–120mm')
        if p['RearTaper']>p['RoofWidth']/8 or p['EdgeBow']>80:raise ValueError('顶盖收窄/边缘弯曲量过大')
    else:
        if not 1350<=p['FenderLength']<=1800 or not 900<=p['FenderHeight']<=1200:raise ValueError('翼子板长1350–1800、高900–1200mm')
        if not 350<=p['WheelRadius']<=470 or not 70<=p['WheelCenterZ']<=140:raise ValueError('轮拱半径350–470、中心高度70–140mm')
        if not 40<=p['Bulge']<=130 or p['ShoulderRise']>60:raise ValueError('鼓包40–130、肩部抬升≤60mm')
        if not 300<=p['MarkerX']<=420 or not 730<=p['MarkerZ']<=790:raise ValueError('开口中心X300–420、Z730–790mm')
        if not 40<=p['MarkerWidth']<=110 or not 20<=p['MarkerHeight']<=50:raise ValueError('开口宽40–110、高20–50mm')
        if p['MarkerX']-p['MarkerWidth']/2<.12*p['FenderLength'] or p['MarkerZ']+p['MarkerHeight']/2>.84*p['FenderHeight']:
            raise ValueError('开口超出演示外板保守安全区域')
    return p


def point(xyz,formulas):return {'xyz':xyz,'formulas':formulas}


def plan(template,values):
    p=validate(template,values)
    profiles=[]
    for i in range(7):
        t=i/6-.5
        row=[]
        for j in range(9):
            s=j/8-.5
            if template=='roof_reference':
                xyz=[1.16*t*p['RoofLength'],1.2*s*p['RoofWidth'],p['LongCrown']*(1-4*(1.16*t)**2)+p['CrossCrown']*(1-4*(1.2*s)**2)]
                f=[f'{1.16*t:.16g} * RoofLength',f'{1.2*s:.16g} * RoofWidth',f'{1-4*(1.16*t)**2:.16g} * LongCrown + {1-4*(1.2*s)**2:.16g} * CrossCrown']
            else:
                # Smooth carrier over the whole irregular panel, independent
                # of the trimming wire; no imported or triangulated geometry.
                z=(s+.5)*1.15
                y1=(1-(2*t)**2)*(1-.6*(z-.5)**2)
                y2=z*(1-z)
                xyz=[1.16*t*p['FenderLength'],y1*p['Bulge']+y2*p['ShoulderRise'],z*p['FenderHeight']]
                f=[f'{1.16*t:.16g} * FenderLength',f'{y1:.16g} * Bulge + {y2:.16g} * ShoulderRise',f'{z:.16g} * FenderHeight']
            row.append(point(xyz,f))
        profiles.append(row)
    result={'template':template,'parameters':p,'profiles':profiles,'reference_image_only':True,
            'scope':'Image-inspired assumed dimensions. Native GSD history, no exact reconstruction or Class-A acceptance.'}
    if template=='roof_reference':
        # Closed smooth footprint, with four rounded corners represented by a
        # periodic spline. Outer side walls are engineering return approximations.
        outline=[]
        footprint=[]
        corners=[(.44,.44,0),(-.44,.44,90),(-.44,-.44,180),(.44,-.44,270)]
        for n,(cx,cy,angle) in enumerate(corners):
            for k in range(5):
                a=math.radians(angle+90*k/4)
                footprint.append((cx+.06*math.cos(a),cy+.06*math.sin(a)))
            ex,ey=footprint[-1]
            nx,ny,na=corners[(n+1)%4]
            sx,sy=nx+.06*math.cos(math.radians(na)),ny+.06*math.sin(math.radians(na))
            footprint.extend((ex+(sx-ex)*k/4,ey+(sy-ey)*k/4) for k in range(1,4))
        for x,y in footprint:
            bow=1-4*y*y
            # Curve both end edges outwards; side-edge midpoints remain fixed.
            sign=1 if x>0 else -1 if x<0 else 0
            xf=f'{x} * RoofLength + {sign*bow} * EdgeBow'
            yf=f'{y} * RoofWidth - {2*x*y} * RearTaper'
            outline.append(point([x*p['RoofLength']+sign*bow*p['EdgeBow'],y*p['RoofWidth']-2*x*y*p['RearTaper'],0],[xf,yf,'0mm']))
        result.update(outline=outline,outline_kind='closed_spline',cut_axis=[0,0,1])
    else:
        # Ordered outer polygon from wheel-arch left endpoint to right endpoint;
        # a smooth semicircular spline closes the wheel opening below the skin.
        outer=[point([-p['WheelRadius'],0,p['WheelCenterZ']],['-WheelRadius','0mm','WheelCenterZ'])]
        for x,z in [(-700,180),(-760,205),(-735,280),(-660,330),(-585,525),(-500,640),(-270,710),(-190,820),(-175,925),(40,1010),(130,930),(95,850),(640,950),(650,250),(700,25),(610,15),(550,150)]:
            outer.append(point([x/1500*p['FenderLength'],0,z/1000*p['FenderHeight']],[f'{x/1500:.16g} * FenderLength','0mm',f'{z/1000:.16g} * FenderHeight']))
        outer.append(point([p['WheelRadius'],0,p['WheelCenterZ']],['WheelRadius','0mm','WheelCenterZ']))
        arch=[]
        for k in range(17):
            a=math.pi*k/16;c,s=math.cos(a),math.sin(a)
            arch.append(point([c*p['WheelRadius'],0,p['WheelCenterZ']+s*p['WheelRadius']],[f'{c:.16g} * WheelRadius','0mm',f'WheelCenterZ + {s:.16g} * WheelRadius']))
        marker=[]
        for k in range(16):
            a=2*math.pi*k/16;c,s=math.cos(a)/2,math.sin(a)/2
            marker.append(point([p['MarkerX']+c*p['MarkerWidth'],0,p['MarkerZ']+s*p['MarkerHeight']],
                                [f'MarkerX + {c:.16g} * MarkerWidth','0mm',f'MarkerZ + {s:.16g} * MarkerHeight']))
        result.update(outline=outer,outline_kind='lines_and_arch',arch=arch,marker=marker,cut_axis=[0,1,0])
    return result
