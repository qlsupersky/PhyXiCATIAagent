# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "catia-sdk-plate"
# revision = "1.0.0"
# ///
"""CATIA integration sample: centered 120 x 90 x 20 mm plate, one through hole."""
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- params ----
    width = scad.var(name="width", default=120.0, unit="mm")
    height = scad.var(name="height", default=90.0, unit="mm")
    thickness = scad.var(name="thickness", default=20.0, unit="mm")
    hole_diameter = scad.var(name="hole_diameter", default=10.0, unit="mm")
    return width, height, thickness, hole_diameter

@app.cell
def _(width, height, thickness, hole_diameter):
    # ---- guard: feasible-dimensions ----
    assert min(float(width), float(height), float(thickness), float(hole_diameter)) > 0
    assert float(hole_diameter) < min(float(width), float(height))
    return

@app.cell
def _(width, height, thickness):
    # ---- feature: plate (build) ----
    plate = scad.make_box_rsolid(width=width, height=height, depth=thickness)
    print("plate volume mm3:", plate.get_volume())
    return (plate,)

@app.cell
def _(hole_diameter, thickness):
    # ---- feature: hole-tool (build) ----
    hole_tool = scad.make_cylinder_rsolid(radius=hole_diameter/2, height=thickness+2,
                                        bottom_face_center=(0, 0, -1))
    return (hole_tool,)

@app.cell
def _(plate, hole_tool):
    # ---- feature: through-hole (bool) ----
    drilled = scad.cut_rsolid(plate, hole_tool, skip_non_intersecting=False)
    print("result faces:", len(scad.ql.faces().resolve(drilled)))
    return (drilled,)

@app.cell
def _(drilled):
    result = scad.Part(part_id="catia-sdk-plate", body=drilled)
    return (result,)

if __name__ == "__main__":
    app.run()
