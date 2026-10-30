"""SDK process boundary. JSON requests and reports; modeling stdout stays in run.log."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import math
import os
import shutil
import traceback
from pathlib import Path


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(step, directory):
    from simplecadapi.inspect import brep
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    shape = brep.load_step_rshape(path=str(step), require_single_root=True, require_valid=True)
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solids)
    if solids.Extent() != 1:
        raise ValueError(f"Expected one solid; STEP contains {solids.Extent()}. Activate a single-body CATPart.")
    solid = TopoDS.Solid_s(solids.FindKey(1))
    if not BRepCheck_Analyzer(solid).IsValid():
        raise ValueError("Imported base topology is invalid.")
    directory = Path(directory).resolve()
    data = directory / "data"
    data.mkdir(parents=True, exist_ok=True)
    dest = data / "base.scadbrep"
    if dest.exists():
        raise FileExistsError(dest)
    brep.copy_step_region_rpath(path=str(step), output_path=dest)
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(solid, bounds, False, False)
    bbox = list(bounds.Get())
    return {"brep": str(dest), "sha256": "sha256:" + hashlib.sha256(dest.read_bytes()).hexdigest(),
            "bounds_mm": bbox, "source_step": str(Path(step).resolve())}


def run(request):
    import simplecadapi as scad
    from simplecadapi.runtime import run_notebook
    from OCP.BRepCheck import BRepCheck_Analyzer
    from importlib.metadata import version
    notebook = Path(request["notebook"]).resolve()
    out = Path(request["output"]).resolve()
    out.mkdir(parents=True, exist_ok=False)
    overrides = request.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object.")
    for key, value in overrides.items():
        if not isinstance(value, (int, float, bool)) or not math.isfinite(value):
            raise ValueError(f"Parameter {key} must be a finite number or boolean.")
    import ast
    tree = ast.parse(notebook.read_text(encoding="utf-8"))
    parameters = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            if (isinstance(callee, ast.Attribute) and callee.attr in ("var", "Var")) or (isinstance(callee, ast.Name) and callee.id in ("var", "Var")):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        parameters[target.id] = node.value
    unknown = set(overrides)-parameters.keys()
    if unknown:
        raise ValueError("Unknown named SDK parameter(s): "+", ".join(sorted(unknown)))
    original_notebook = notebook
    if overrides:
        # In SDK 2.2.1 runtime overrides skip the whole declaring cell. Patch
        # only var default expressions in a private copy instead, retaining
        # units and recorded named parameters in the durable feature graph.
        source_copy = out / "notebook-source"
        if out.is_relative_to(notebook.parent):
            raise ValueError("Output directory must be outside the notebook workspace")
        shutil.copytree(notebook.parent, source_copy, ignore=shutil.ignore_patterns(
            "__marimo__", ".sca-editor", "__pycache__", ".git", "*.CATPart", "*.CATProduct"))
        notebook = source_copy / notebook.name
        raw = notebook.read_bytes()
        lines = raw.splitlines(keepends=True)
        edits = []
        for key, value in overrides.items():
            call = parameters[key]
            default = next((kw.value for kw in call.keywords if kw.arg == "default"), None)
            if default is None and len(call.args) > 1:
                default = call.args[1]
            if default is None:
                raise ValueError(f"Parameter {key} has no editable default")
            begin = sum(map(len, lines[:default.lineno-1])) + default.col_offset
            end = sum(map(len, lines[:default.end_lineno-1])) + default.end_col_offset
            edits.append((begin, end, repr(value).encode("ascii")))
        for begin, end, replacement in sorted(edits, reverse=True):
            raw = raw[:begin] + replacement + raw[end:]
        notebook.write_bytes(raw)
    # relative hash-pinned inputs must resolve in the notebook's workspace
    os.chdir(notebook.parent)
    with (out / "run.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        # Long Windows workspace paths can exceed native cache writer limits.
        product_run = run_notebook(path=notebook, cache=False)
        product = product_run.product
        if not isinstance(product, scad.Part):
            raise ValueError("The CATIA bridge currently accepts a single Part notebook; assemblies are unsupported.")
        if not BRepCheck_Analyzer(product.body.wrapped).IsValid():
            raise ValueError("SDK produced invalid topology.")
        volume = product.body.get_volume()
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("SDK produced a non-positive volume.")
        if len(scad.ql.solids().resolve(product.body)) != 1:
            raise ValueError("SDK result must contain exactly one solid.")
        package = out / "model.scadpkg"
        step = out / "model.step"
        scad.capture(product_run.definition, package)
        scad.exporter.export_product_package_to_step(data=package, output_path=step)
        facts = {"valid": True, "solid_count": len(scad.ql.solids().resolve(product.body)),
                 "face_count": len(scad.ql.faces().resolve(product.body)), "volume_mm3": volume}
    result = {"ok": True, "notebook": str(original_notebook), "executed_notebook": str(notebook), "notebook_sha256": hashlib.sha256(notebook.read_bytes()).hexdigest(),
              "overrides": overrides, "simplecadapi_version": version("simplecadapi"), "facts": facts,
              "package": str(package), "step": str(step), "output": str(out),
              "cells": [{"key": c.key, "status": c.status} for c in product_run.cells]}
    dump(out / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("response", type=Path)
    args = parser.parse_args()
    args.request = args.request.resolve()
    args.response = args.response.resolve()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        if request["action"] == "prepare":
            result = {"ok": True, "base": prepare(request["step"], request["directory"])}
        elif request["action"] == "run":
            result = run(request)
        elif request["action"] == "inspect-surface":
            from surface_quality import analyze
            quality = analyze(request['output'],request['offset'],request.get('template'),request.get('parameters'))
            dump(Path(request['output'])/'surface-quality.json',quality)
            result = {'ok':True,'quality':quality}
        elif request['action'] == 'inspect-housing':
            from housing import inventory
            result={'ok':True,'inventory':inventory(request['step'],request.get('axis','Y'))}
        elif request['action'] == 'plan-housing-groove':
            from housing import make_plan
            result={'ok':True,'plan':make_plan(**request['arguments'])}
        elif request["action"] == "analyze-sections":
            from section_analysis import analyze
            result = {'ok': True, 'analysis': analyze(request['step'], request['directory'],
                      request.get('reference_axis','Z'), request.get('fractions'))}
        else:
            raise ValueError("Unknown SDK action.")
        dump(args.response, result)
    except Exception as exc:
        dump(args.response, {"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
