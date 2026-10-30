# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "catia-brake_disc-demo"
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
    OuterDiameter = scad.var(name="OuterDiameter", default=320, unit="mm")
    BoreDiameter = scad.var(name="BoreDiameter", default=70, unit="mm")
    DiscThickness = scad.var(name="DiscThickness", default=28, unit="mm")
    HatDiameter = scad.var(name="HatDiameter", default=150, unit="mm")
    HatHeight = scad.var(name="HatHeight", default=12, unit="mm")
    BoltPCD = scad.var(name="BoltPCD", default=114.3, unit="mm")
    BoltHoleDiameter = scad.var(name="BoltHoleDiameter", default=14, unit="mm")
    BoltCount = scad.var(name="BoltCount", default=5)
    VentCount = scad.var(name="VentCount", default=24)
    VentInnerRadius = scad.var(name="VentInnerRadius", default=85, unit="mm")
    VentWidth = scad.var(name="VentWidth", default=7, unit="mm")
    SkinThickness = scad.var(name="SkinThickness", default=6, unit="mm")
    return OuterDiameter, BoreDiameter, DiscThickness, HatDiameter, HatHeight, BoltPCD, BoltHoleDiameter, BoltCount, VentCount, VentInnerRadius, VentWidth, SkinThickness

@app.cell
def _(OuterDiameter, BoreDiameter, DiscThickness, HatDiameter, HatHeight, BoltPCD, BoltHoleDiameter, BoltCount, VentCount, VentInnerRadius, VentWidth, SkinThickness):
    # ---- guard: bounded-demo-parameters ----
    assert all(0 < float(_v) <= 2000 for _v in (OuterDiameter, BoreDiameter, DiscThickness, HatDiameter, HatHeight, BoltPCD, BoltHoleDiameter, BoltCount, VentCount, VentInnerRadius, VentWidth, SkinThickness))
    assert float(BoltCount) == int(float(BoltCount)) and 3 <= int(float(BoltCount)) <= 64
    assert float(VentCount) == int(float(VentCount)) and 3 <= int(float(VentCount)) <= 64
    assert float(BoreDiameter)+float(BoltHoleDiameter) < float(BoltPCD)
    assert float(BoltPCD)+float(BoltHoleDiameter) < float(HatDiameter)
    assert float(BoltHoleDiameter) < float(BoltPCD)*math.sin(math.pi/int(float(BoltCount)))
    assert float(HatDiameter)/2 < float(VentInnerRadius) < float(OuterDiameter)/2-5
    assert 2*float(SkinThickness) < float(DiscThickness)
    assert float(VentWidth) < 2*float(VentInnerRadius)*math.sin(math.pi/int(float(VentCount)))
    return

@app.cell
def _(OuterDiameter, DiscThickness):
    # ---- feature: rotor-blank (build) ----
    rotor_blank = scad.make_cylinder_rsolid(radius=OuterDiameter/2, height=DiscThickness)
    return (rotor_blank,)

@app.cell
def _(rotor_blank, HatDiameter, HatHeight, DiscThickness):
    # ---- feature: mounting-hat (add) ----
    _hat = scad.make_cylinder_rsolid(radius=HatDiameter/2, height=HatHeight, bottom_face_center=(0,0,DiscThickness))
    mounting_hat = scad.union_rsolid(rotor_blank, _hat)
    return (mounting_hat,)

@app.cell
def _(mounting_hat, OuterDiameter, VentInnerRadius, VentWidth, VentCount, SkinThickness, DiscThickness):
    # ---- feature: radial-vent-slots (subtract) ----
    _end = OuterDiameter/2+2
    _length = _end-VentInnerRadius
    _seed = scad.make_box_rsolid(width=_length, height=VentWidth, depth=DiscThickness-2*SkinThickness,
                                 bottom_face_center=((_end+VentInnerRadius)/2,0,SkinThickness))
    _tools = [scad.rotate_shape(shape=_seed, angle=360*_i/int(float(VentCount)), axis=(0,0,1), origin=(0,0,0))
              for _i in range(int(float(VentCount)))]
    ventilated = scad.cut_rsolid(mounting_hat, _tools, skip_non_intersecting=False)
    return (ventilated,)

@app.cell
def _(ventilated, BoreDiameter, DiscThickness, HatHeight):
    # ---- feature: central-bore (subtract) ----
    _tool = scad.make_cylinder_rsolid(radius=BoreDiameter/2, height=DiscThickness+HatHeight+2, bottom_face_center=(0,0,-1))
    central_bore = scad.cut_rsolid(ventilated, _tool, skip_non_intersecting=False)
    return (central_bore,)

@app.cell
def _(central_bore, BoltPCD, BoltHoleDiameter, BoltCount, DiscThickness, HatHeight):
    # ---- feature: mounting-holes (subtract) ----
    _holes = [scad.make_cylinder_rsolid(radius=BoltHoleDiameter/2, height=DiscThickness+HatHeight+2,
              bottom_face_center=(BoltPCD/2*math.cos(2*math.pi*_i/int(float(BoltCount))),
                                  BoltPCD/2*math.sin(2*math.pi*_i/int(float(BoltCount))),-1))
              for _i in range(int(float(BoltCount)))]
    mounting_holes = scad.cut_rsolid(central_bore, _holes, skip_non_intersecting=False)
    return (mounting_holes,)

@app.cell
def _(mounting_holes):
    result = scad.Part(part_id="catia-brake_disc-demo", body=mounting_holes)
    return (result,)

if __name__ == "__main__":
    app.run()
