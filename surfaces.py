"""Bounded native CATIA GSD demonstrations; no Class-A certification."""
import math
from pathlib import Path
import style_surfaces

CATALOG = {
    "roof": {"label": "顶盖双曲率外板演示", "defaults": {
        "RoofLength": 1800, "RoofWidth": 1400, "LongCrown": 80,
        "CrossCrown": 50, "TrimMargin": 40, "OffsetDistance": 1.2}},
    "fender": {"label": "翼子板轮拱局部曲面演示", "defaults": {
        "WheelRadius": 360, "BandWidth": 220, "Bulge": 65,
        "EdgeRise": 15, "TrimHeight": 60, "OffsetDistance": 1.2}}
}
CATALOG.update(style_surfaces.CATALOG)


def validate(template, parameters=None):
    if template in style_surfaces.CATALOG:
        return style_surfaces.validate(template, parameters)
    if template not in CATALOG:
        raise ValueError("曲面模板仅支持 roof / fender")
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError("曲面参数必须为 JSON 对象")
    defaults = CATALOG[template]["defaults"]
    if set(parameters or {}) - defaults.keys():
        raise ValueError("包含未知曲面参数")
    p = {**defaults, **(parameters or {})}
    for name, value in p.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 5000:
            raise ValueError(name + " 必须为有限正数，最大5000mm")
    if not .1 <= p['OffsetDistance'] <= 5:
        raise ValueError("演示偏置距离须在0.1–5mm范围内")
    if template == 'roof':
        if min(p['RoofLength'], p['RoofWidth']) < 500 or p['TrimMargin'] >= p['RoofLength']/4:
            raise ValueError("顶盖长宽至少500mm，裁剪余量须小于长度的1/4")
        if max(p['LongCrown'], p['CrossCrown']) > min(p['RoofLength'], p['RoofWidth'])/4:
            raise ValueError("拱高超出演示曲面范围")
    elif not (150 <= p['WheelRadius'] <= 800 and 40 <= p['BandWidth'] <= 500 and p['TrimHeight'] < p['WheelRadius']/2 and p['Bulge'] < p['BandWidth']/2):
        raise ValueError("轮拱半径/带宽/裁剪高度/鼓包超出演示范围")
    return p


def plan(template, parameters):
    if template in style_surfaces.CATALOG:
        return style_surfaces.plan(template, parameters)
    p = validate(template, parameters)
    profiles = []
    for i in range(5):
        t = i/4
        points = []
        for j in range(9):
            s = j/8
            if template == 'roof':
                fx, fy = t-.5, s-.5
                point = [fx*p['RoofLength'], fy*p['RoofWidth'], p['LongCrown']*(1-4*fx*fx)+p['CrossCrown']*(1-4*fy*fy)]
                formulas = [f"{fx} * RoofLength", f"{fy} * RoofWidth", f"{1-4*fx*fx} * LongCrown + {1-4*fy*fy} * CrossCrown"]
            else:
                # Radial cross sections progress around the arch, avoiding
                # parallel section planes which reverse order at the bulge.
                a = math.pi*t
                r = p['WheelRadius']+s*p['BandWidth']
                point = [r*math.cos(a), p['Bulge']*4*s*(1-s)+p['EdgeRise']*s, r*math.sin(a)]
                formulas = [f"{math.cos(a):.16g} * (WheelRadius + {s} * BandWidth)", f"{4*s*(1-s)} * Bulge + {s} * EdgeRise", f"{math.sin(a):.16g} * (WheelRadius + {s} * BandWidth)"]
            points.append({'xyz': point, 'formulas': formulas})
        profiles.append(points)
    return {'template': template, 'parameters': p, 'profiles': profiles,
            'scope': 'Demonstration only. Native GSD history; not customer geometry or Class-A acceptance.'}


def review_sources(root):
    """Bind review to the generator and compiled bridge, including native source."""
    import hashlib
    names = ['surfaces.py', 'style_surfaces.py', 'bridge/SurfaceBuilder.cs', 'bridge/StyleSurfaceBuilder.cs', 'bridge/CatiaBridge.cs', 'bin/CatiaBridge.exe']
    files = {name: hashlib.sha256((Path(root)/name).read_bytes()).hexdigest() for name in names}
    token = hashlib.sha256(repr(sorted(files.items())).encode()).hexdigest()
    return token, files
