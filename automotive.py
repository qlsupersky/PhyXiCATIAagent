"""Bounded SimpleCADAPI automotive demonstration templates (mm)."""
import math

CATALOG = {
    "brake_disc": {"label": "SimpleCADAPI 通风制动盘演示", "notebook": "brake_disc.py", "defaults": {
        "OuterDiameter": 320, "BoreDiameter": 70, "DiscThickness": 28,
        "HatDiameter": 150, "HatHeight": 12, "BoltPCD": 114.3,
        "BoltHoleDiameter": 14, "BoltCount": 5, "VentCount": 24,
        "VentInnerRadius": 85, "VentWidth": 7, "SkinThickness": 6}},
    "wheel": {"label": "SimpleCADAPI 轮毂演示", "notebook": "wheel.py", "defaults": {
        "OuterDiameter": 460, "RimInnerDiameter": 420, "RimWidth": 180,
        "HubDiameter": 140, "BoreDiameter": 65, "HubThickness": 35,
        "SpokeCount": 8, "SpokeWidth": 28, "SpokeThickness": 22,
        "BoltPCD": 114.3, "BoltHoleDiameter": 14, "BoltCount": 5}}
}


def validate(template, parameters=None):
    if template not in CATALOG:
        raise ValueError("仅支持 brake_disc / wheel 演示模板，A级曲面尚未实现")
    defaults = CATALOG[template]["defaults"]
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError("参数必须为 JSON 对象")
    if set(parameters or {})-defaults.keys():
        raise ValueError("参数必须为对象，且不能包含未知参数")
    values = {**defaults, **(parameters or {})}
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 2000:
            raise ValueError(f"{name} 必须为 0 到 2000 之间的有限正数")
        if name.endswith("Count") and (value != int(value) or not 3 <= value <= 64):
            raise ValueError(f"{name} 必须为 3 到 64 之间的整数")
    p = values
    if not p["BoreDiameter"]+p["BoltHoleDiameter"] < p["BoltPCD"]:
        raise ValueError("安装孔与中心孔相交")
    hub = p["HatDiameter"] if template == "brake_disc" else p["HubDiameter"]
    if p["BoltPCD"]+p["BoltHoleDiameter"] >= hub:
        raise ValueError("安装孔超出轮毂/盘帽范围")
    if p["BoltHoleDiameter"] >= p["BoltPCD"]*math.sin(math.pi/p["BoltCount"]):
        raise ValueError("相邻安装孔相交")
    if template == "brake_disc":
        if not hub/2 < p["VentInnerRadius"] < p["OuterDiameter"]/2 - 5:
            raise ValueError("通风槽必须位于盘帽外、盘外缘内")
        if 2*p["SkinThickness"] >= p["DiscThickness"]:
            raise ValueError("上下摩擦面厚度之和必须小于盘厚")
        if p["VentWidth"] >= 2*p["VentInnerRadius"]*math.sin(math.pi/p["VentCount"]):
            raise ValueError("相邻通风槽相交")
    else:
        if not p["HubDiameter"] < p["RimInnerDiameter"] < p["OuterDiameter"]:
            raise ValueError("轮毂直径、轮辋内径、外径必须递增")
        if p["SpokeThickness"] > min(p["RimWidth"], p["HubThickness"]):
            raise ValueError("辐条厚度不能超过轮辋宽度或轮心厚度")
        if p["SpokeWidth"] >= p["HubDiameter"]*math.sin(math.pi/p["SpokeCount"]):
            raise ValueError("辐条在轮心处重叠，请减小宽度或数量")
    return values
