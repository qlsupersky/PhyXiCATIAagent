# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "catia-wheel-demo"
# revision = "0.2.0"
# ///
"""SDK integration demonstration; no customer dimensions or automotive release validation.
Units mm, Z axis, origin at bottom center. Not a production wheel/brake design.
"""
import marimo
app = marimo.App()
with app.setup:
    import math
    import simplecadapi as scad

@app.cell
def _():
    # ---- params ----
    OuterDiameter = scad.var(name="OuterDiameter", default=460, unit="mm")
    RimInnerDiameter = scad.var(name="RimInnerDiameter", default=420, unit="mm")
    RimWidth = scad.var(name="RimWidth", default=180, unit="mm")
    HubDiameter = scad.var(name="HubDiameter", default=140, unit="mm")
    BoreDiameter = scad.var(name="BoreDiameter", default=65, unit="mm")
    HubThickness = scad.var(name="HubThickness", default=35, unit="mm")
    SpokeCount = scad.var(name="SpokeCount", default=8)
    SpokeWidth = scad.var(name="SpokeWidth", default=28, unit="mm")
    SpokeThickness = scad.var(name="SpokeThickness", default=22, unit="mm")
    BoltPCD = scad.var(name="BoltPCD", default=114.3, unit="mm")
    BoltHoleDiameter = scad.var(name="BoltHoleDiameter", default=14, unit="mm")
    BoltCount = scad.var(name="BoltCount", default=5)
    return OuterDiameter, RimInnerDiameter, RimWidth, HubDiameter, BoreDiameter, HubThickness, SpokeCount, SpokeWidth, SpokeThickness, BoltPCD, BoltHoleDiameter, BoltCount

@app.cell
def _(OuterDiameter, RimInnerDiameter, RimWidth, HubDiameter, BoreDiameter, HubThickness, SpokeCount, SpokeWidth, SpokeThickness, BoltPCD, BoltHoleDiameter, BoltCount):
    # ---- guard: bounded-demo-parameters ----
    assert all(0 < float(_v) <= 2000 for _v in (OuterDiameter, RimInnerDiameter, RimWidth, HubDiameter, BoreDiameter, HubThickness, SpokeCount, SpokeWidth, SpokeThickness, BoltPCD, BoltHoleDiameter, BoltCount))
    assert float(SpokeCount) == int(float(SpokeCount)) and 3 <= int(float(SpokeCount)) <= 64
    assert float(BoltCount) == int(float(BoltCount)) and 3 <= int(float(BoltCount)) <= 64
    assert float(BoreDiameter)+float(BoltHoleDiameter) < float(BoltPCD)
    assert float(BoltPCD)+float(BoltHoleDiameter) < float(HubDiameter)
    assert float(BoltHoleDiameter) < float(BoltPCD)*math.sin(math.pi/int(float(BoltCount)))
    assert float(HubDiameter) < float(RimInnerDiameter) < float(OuterDiameter)
    assert float(SpokeThickness) <= min(float(RimWidth), float(HubThickness))
    assert float(SpokeWidth) < float(HubDiameter)*math.sin(math.pi/int(float(SpokeCount)))
    return

@app.cell
def _(HubDiameter, HubThickness):
    # ---- feature: wheel-hub (build) ----
    wheel_hub = scad.make_cylinder_rsolid(radius=HubDiameter/2, height=HubThickness)
    return (wheel_hub,)

@app.cell
def _(wheel_hub, HubDiameter, RimInnerDiameter, OuterDiameter, SpokeWidth, SpokeThickness, SpokeCount):
    # ---- feature: radial-spokes (add) ----
    _start = HubDiameter*0.425
    _end = (OuterDiameter+RimInnerDiameter)/4
    _seed = scad.make_box_rsolid(width=_end-_start, height=SpokeWidth, depth=SpokeThickness,
                                 bottom_face_center=((_start+_end)/2,0,0))
    _spokes = [scad.rotate_shape(shape=_seed, angle=360*_i/int(float(SpokeCount)), axis=(0,0,1), origin=(0,0,0))
               for _i in range(int(float(SpokeCount)))]
    spoked_hub = scad.union_rsolid(wheel_hub, _spokes)
    return (spoked_hub,)

@app.cell
def _(OuterDiameter, RimInnerDiameter, RimWidth):
    # ---- feature: annular-rim (subtract) ----
    _outer = scad.make_cylinder_rsolid(radius=OuterDiameter/2, height=RimWidth)
    _inner = scad.make_cylinder_rsolid(radius=RimInnerDiameter/2, height=RimWidth+2, bottom_face_center=(0,0,-1))
    annular_rim = scad.cut_rsolid(_outer, _inner, skip_non_intersecting=False)
    return (annular_rim,)

@app.cell
def _(spoked_hub, annular_rim):
    # ---- feature: rim-to-spokes (add) ----
    rim_to_spokes = scad.union_rsolid(spoked_hub, annular_rim)
    return (rim_to_spokes,)

@app.cell
def _(rim_to_spokes, BoreDiameter, RimWidth):
    # ---- feature: central-bore (subtract) ----
    _tool = scad.make_cylinder_rsolid(radius=BoreDiameter/2, height=RimWidth+2, bottom_face_center=(0,0,-1))
    central_bore = scad.cut_rsolid(rim_to_spokes, _tool, skip_non_intersecting=False)
    return (central_bore,)

@app.cell
def _(central_bore, BoltPCD, BoltHoleDiameter, BoltCount, RimWidth):
    # ---- feature: mounting-holes (subtract) ----
    _holes = [scad.make_cylinder_rsolid(radius=BoltHoleDiameter/2, height=RimWidth+2,
              bottom_face_center=(BoltPCD/2*math.cos(2*math.pi*_i/int(float(BoltCount))),
                                  BoltPCD/2*math.sin(2*math.pi*_i/int(float(BoltCount))),-1))
              for _i in range(int(float(BoltCount)))]
    mounting_holes = scad.cut_rsolid(central_bore, _holes, skip_non_intersecting=False)
    return (mounting_holes,)

@app.cell
def _(mounting_holes):
    result = scad.Part(part_id="catia-wheel-demo", body=mounting_holes)
    return (result,)

if __name__ == "__main__":
    app.run()
