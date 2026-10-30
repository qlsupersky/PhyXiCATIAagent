"""Create user-editable notebook workspaces, never modify imported source geometry."""
from pathlib import Path
import json

SEAL_DEFAULTS = {"GrooveLength": 100., "GrooveWidth": 70., "TopWidth": 3.05,
                 "Depth": 4., "DraftDeg": 1.5, "FloorRadius": .5,
                 "HoleInset": 12., "TapHoleDia": 3.3, "TapHoleDepth": 14.,
                 "BossDia": 9., "StudLength": 18., "CenterX": 0., "CenterY": 0., "TopZ": 20.}


def write_seal(directory, base):
    directory = Path(directory)
    defaults = dict(SEAL_DEFAULTS)
    xmin, ymin, zmin, xmax, ymax, zmax = base["bounds_mm"]
    defaults.update(CenterX=round((xmin+xmax)/2, 6), CenterY=round((ymin+ymax)/2, 6), TopZ=round(zmax, 6))
    defaults["GrooveLength"] = round((xmax-xmin)-20, 6)
    defaults["GrooveWidth"] = round((ymax-ymin)-20, 6)
    declarations = "\n".join(f'    {key} = scad.var(name="{key}", default={value!r}, unit="{ "deg" if key == "DraftDeg" else "mm"}")'
                               for key, value in defaults.items())
    source = SEAL_SOURCE.replace("__PARAMS__", declarations).replace("__HASH__", base["sha256"])
    notebook = directory / "seal.py"
    if notebook.exists():
        raise FileExistsError(notebook)
    notebook.write_text(source, encoding="utf-8")
    manifest = {"kind": "rectangular-xy-seal", "notebook": str(notebook.resolve()), "defaults": defaults,
                "base": base, "active": True, "revision": 0,
                "limitations": ["XY planar face only", "four bosses and blind tap-drill bores",
                                "no helical or CATIA cosmetic threads", "notebook history; CATIA imported solid"]}
    (directory / "feature.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


SEAL_SOURCE = '''# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "catia-rectangular-seal"
# revision = "1.0.0"
# inputs = ["data/base.scadbrep"]
# ///
"""Rectangular groove on an XY face; four raised bosses with blind tap-drill bores.
TopWidth is FLOOR width. DraftDeg widens the opening. No modeled threads.
Delete is rebuilt from the preserved base; never subtract features from an edited result.
"""
import marimo
app = marimo.App()
with app.setup:
    import math
    import simplecadapi as scad

@app.function
def rectangular_loop(sketch, prefix, length, width):
    _corners = [(-length/2, -width/2), (length/2, -width/2), (length/2, width/2), (-length/2, width/2)]
    for _i, (_x, _y) in enumerate(_corners):
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=f"{prefix}p{_i}", x=_x, y=_y)
        sketch = scad.constrain_fix_rsketch(sketch=sketch, target=f"{prefix}p{_i}")
    for _i in range(4):
        sketch = scad.add_line_rsketch(sketch=sketch, entity_id=f"{prefix}l{_i}",
                                     start=f"{prefix}p{_i}", end=f"{prefix}p{(_i+1)%4}")
    return sketch

@app.cell
def _():
    # ---- params ----
__PARAMS__
    return (GrooveLength, GrooveWidth, TopWidth, Depth, DraftDeg, FloorRadius, HoleInset,
            TapHoleDia, TapHoleDepth, BossDia, StudLength, CenterX, CenterY, TopZ)

@app.cell
def _():
    # ---- feature: imported-base (build) ----
    base_body = scad.load_brep_region_rsolid(path="data/base.scadbrep", sha256="__HASH__", tag_prefix="source")
    return (base_body,)

@app.cell
def _(base_body, TopZ, GrooveLength, GrooveWidth, TopWidth, Depth, DraftDeg, FloorRadius,
      HoleInset, TapHoleDia, TapHoleDepth, BossDia, StudLength, CenterX, CenterY):
    # ---- guard: feasibility-and-horizontal-face ----
    _l, _w, _t, _d, _a, _r = map(float, (GrooveLength, GrooveWidth, TopWidth, Depth, DraftDeg, FloorRadius))
    _opening = _t + 2*_d*math.tan(math.radians(_a))
    assert min(_l, _w, _t, _d) > 0, "Groove dimensions must be positive"
    assert 0 <= _a < 20, "Draft angle must be in [0,20) degrees"
    assert 0 <= _r < _t/2, "FloorRadius must be below half the floor width"
    assert min(_l, _w) > 2*_opening, "Groove collapses"
    assert float(HoleInset) > _opening + float(BossDia)/2, "Bosses overlap groove"
    assert float(HoleInset) < min(_l, _w)/2 - float(BossDia)/2, "Bosses overlap each other"
    assert 0 < float(TapHoleDia) < float(BossDia)
    assert 0 < float(TapHoleDepth) < float(StudLength), "Blind bore depth must be below boss height"
    _face = scad.ql.faces().where(scad.ql.and_(
        scad.ql.prop("geom.type", "==", "PLANE"),
        scad.ql.prop("geom.normal.z", ">=", .999),
        scad.ql.prop("geom.center.z", ">=", float(TopZ)-.001),
        scad.ql.prop("geom.center.z", "<=", float(TopZ)+.001),
    )).order_by(scad.ql.value("geom.area"), desc=True).take(1).exactly(1)
    print("horizontal sealing faces:", len(_face.resolve(base_body)))
    return

@app.cell
def _(GrooveLength, GrooveWidth, TopWidth, Depth, DraftDeg, CenterX, CenterY, TopZ):
    # ---- feature: groove-profile (sketch) ----
    opening_width = float(TopWidth) + 2*float(Depth)*math.tan(math.radians(float(DraftDeg)))
    groove_sketch = scad.make_sketch_rsketch(name="seal-profile", plane={
        "origin": (CenterX, CenterY, TopZ), "x_axis": (1,0,0), "y_axis": (0,1,0)})
    groove_sketch = rectangular_loop(groove_sketch, "outer", GrooveLength, GrooveWidth)
    groove_sketch = rectangular_loop(groove_sketch, "inner", GrooveLength-2*opening_width, GrooveWidth-2*opening_width)
    groove_face = scad.make_face_from_sketch_rface(sketch=groove_sketch, profile=0, inner_profiles=(1,), require_fully_constrained=True)
    return groove_face, opening_width

@app.cell
def _(groove_face, Depth, DraftDeg):
    # ---- feature: drafted-groove-tool (build) ----
    groove_tool = scad.extrude_taper_rsolid(profile=groove_face, vector=(0,0,-Depth), taper=DraftDeg, flip_inner=True)
    print("groove tool mm3:", groove_tool.get_volume())
    return (groove_tool,)

@app.cell
def _(base_body, groove_tool):
    # ---- feature: cut-groove (bool) ----
    grooved = scad.cut_rsolid(base_body, groove_tool, skip_non_intersecting=False)
    assert abs(base_body.get_volume()-grooved.get_volume()-groove_tool.get_volume()) < .01, "Groove is not fully contained in base"
    return (grooved,)

@app.cell
def _(grooved, TopZ, Depth, FloorRadius):
    # ---- feature: groove-floor-fillet (modifier) ----
    if float(FloorRadius) > 0:
        _floor_z = float(TopZ)-float(Depth)
        _edges = scad.ql.edges().where(scad.ql.and_(
            scad.ql.prop("geom.type", "==", "LINE"),
            scad.ql.prop("geom.center.z", ">=", _floor_z-.001),
            scad.ql.prop("geom.center.z", "<=", _floor_z+.001))).exactly(8)
        print("floor edges:", len(_edges.resolve(grooved)))
        rounded_groove = scad.fillet_rsolid(solid=grooved, edges=_edges, radius=FloorRadius)
    else:
        rounded_groove = grooved
    return (rounded_groove,)

@app.cell
def _(GrooveLength, GrooveWidth, HoleInset, CenterX, CenterY, TopZ, BossDia, StudLength):
    # ---- feature: four-bosses (build) ----
    boss_positions = [(CenterX+_sx*(GrooveLength/2-HoleInset), CenterY+_sy*(GrooveWidth/2-HoleInset))
                      for _sx in (-1,1) for _sy in (-1,1)]
    bosses = [scad.make_cylinder_rsolid(radius=BossDia/2, height=StudLength, bottom_face_center=(_x,_y,TopZ))
              for _x, _y in boss_positions]
    return bosses, boss_positions

@app.cell
def _(rounded_groove, bosses):
    # ---- feature: join-bosses (bool) ----
    joined = scad.union_rsolid(rounded_groove, bosses)
    assert abs(joined.get_volume()-rounded_groove.get_volume()-sum(_b.get_volume() for _b in bosses)) < .01, "Bosses do not fully touch the base"
    return (joined,)

@app.cell
def _(boss_positions, TopZ, StudLength, TapHoleDia, TapHoleDepth):
    # ---- feature: four-blind-bore-tools (build) ----
    bore_tools = [scad.make_cylinder_rsolid(radius=TapHoleDia/2, height=TapHoleDepth+1,
                  bottom_face_center=(_x,_y,TopZ+StudLength+1), axis=(0,0,-1)) for _x,_y in boss_positions]
    return (bore_tools,)

@app.cell
def _(joined, bore_tools, TapHoleDia, TapHoleDepth):
    # ---- feature: cut-blind-bores (bool) ----
    sealed_body = scad.cut_rsolid(joined, bore_tools, skip_non_intersecting=False)
    assert abs(joined.get_volume()-sealed_body.get_volume()-math.pi*float(TapHoleDia)**2*float(TapHoleDepth)) < .01, "Unexpected blind bore removal volume"
    print("sealed solid count:", len(scad.ql.solids().resolve(sealed_body)))
    return (sealed_body,)

@app.cell
def _(sealed_body):
    result = scad.Part(part_id="catia-rectangular-seal", body=sealed_body)
    return (result,)

if __name__ == "__main__":
    app.run()
'''
