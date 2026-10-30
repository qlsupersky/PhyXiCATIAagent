from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from templates import write_seal

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def save_snapshot(folder, snapshot):
    import xml.etree.ElementTree as ET
    save_json(Path(folder)/"snapshot.json", snapshot)
    root = ET.Element("CATIASnapshot", {"schema": "phyxi-catia-0.1", "units": "mm"})
    for key in ("application", "document", "path", "volume_mm3"):
        if key in snapshot:
            ET.SubElement(root, key).text = str(snapshot[key])
    bodies = ET.SubElement(root, "Bodies")
    for body in snapshot.get("bodies", []):
        element = ET.SubElement(bodies, "Body", {"name": body["name"]})
        for name in body["features"]:
            ET.SubElement(element, "Feature", {"name": name})
    hybrid = ET.SubElement(root, "HybridBodies")
    for body in snapshot.get("hybrid_bodies", []):
        element = ET.SubElement(hybrid, "HybridBody", {"name": body["name"]})
        for name in body["features"]:
            ET.SubElement(element, "Feature", {"name": name})
    selection = ET.SubElement(root, "Selection")
    for name in snapshot.get("selection", []):
        ET.SubElement(selection, "Item").text = name
    parameters = ET.SubElement(root, "Parameters", {"truncated": str(snapshot.get("parameters_truncated", False)).lower()})
    for parameter in snapshot.get("parameters", []):
        ET.SubElement(parameters, "Parameter", {"name": parameter["name"]}).text = str(parameter["value"])
    ET.indent(root)
    ET.ElementTree(root).write(Path(folder)/"snapshot.xml", encoding="utf-8", xml_declaration=True)


class Controller:
    root = ROOT
    def __init__(self, workspace, logger=print):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log = logger
        self.cancel = threading.Event()
        self.active_process = None
        from native_gate import SessionGate
        native_config = read_json(ROOT/'config.json') if (ROOT/'config.json').exists() else {}
        self.native_gate = SessionGate(native_config.get('native_gate_path') or self.workspace/'native-modeling'/'execution.sqlite')

    def stop(self):
        self.cancel.set()
        active = self.active_process
        if active and active[1] and active[0].poll() is None:
            try:
                active[0].terminate()
            except OSError:
                pass

    def fresh(self, group):
        path = self.workspace / group / (time.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8])
        path.mkdir(parents=True, exist_ok=False)
        return path

    def process(self, command, cancellable=False, timeout=300):
        if self.cancel.is_set():
            raise RuntimeError("任务已中止")
        child = subprocess.Popen([str(c) for c in command], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
        self.active_process = (child, cancellable)
        start = time.monotonic()
        while True:
            try:
                stdout, stderr = child.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                if (cancellable and self.cancel.is_set()) or time.monotonic()-start > timeout:
                    child.terminate()
                    child.communicate(timeout=10)
                    self.active_process = None
                    if cancellable:
                        raise RuntimeError("SDK 任务已中止或超时，未继续导入 CATIA")
                    raise RuntimeError("CATIA 自动化调用超时；请检查 CATIA 是否有对话框，操作可能仍在 CATIA 内完成")
        self.active_process = None
        if cancellable and self.cancel.is_set():
            raise RuntimeError("SDK 任务已中止，未继续导入 CATIA")
        return child.returncode, stdout, stderr

    def bridge(self, *args):
        token = self.native_gate.acquire('legacy_bridge:' + str(args[0] if args else 'unknown'))
        audit = self.fresh('legacy-cad-audit')
        try:
            code, stdout, stderr = self.process([ROOT/"bin"/"CatiaBridge.exe", *args], timeout=180)
            (audit/'stdout.jsonl').write_text(stdout, encoding='utf-8')
            (audit/'stderr.log').write_text(stderr, encoding='utf-8')
            response = json.loads(stdout.strip().splitlines()[-1])
            if code or not response.get("ok"):
                raise RuntimeError(response.get("error", stderr))
            self.native_gate.complete(token, {'bridge_returned': True, 'audit': str(audit)})
            return response["result"]
        except BaseException:
            self.native_gate.freeze(token, 'Legacy bridge did not return accepted evidence; inspect ' + str(audit))
            raise

    def sdk(self, request):
        job = self.fresh("jobs")
        save_json(job/"request.json", request)
        code, stdout, stderr = self.process([sys.executable, ROOT/"worker.py", job/"request.json", job/"response.json"],
                                            cancellable=True, timeout=900)
        (job/"process.log").write_text(stdout+"\n"+stderr, encoding="utf-8")
        if not (job/"response.json").exists():
            raise RuntimeError(f"SDK 未生成响应，请查看 {job / 'process.log'}")
        response = read_json(job/"response.json")
        if code or not response.get("ok"):
            raise RuntimeError(response.get("error", "SDK failed"))
        return response

    def info(self):
        return self.bridge("info")

    def analyze_surface_sections(self, reference_axis='Z', fractions=None, include_images=True):
        if reference_axis not in ('X','Y','Z'):
            raise ValueError('reference_axis must be X/Y/Z')
        if not isinstance(include_images, bool):
            raise ValueError('include_images must be boolean')
        if fractions is not None and (not isinstance(fractions,list) or not 1<=len(fractions)<=5 or
                any(isinstance(f,bool) or not isinstance(f,(int,float)) or not 0<f<1 for f in fractions)):
            raise ValueError('截面位置应为 1–5 个 (0,1) 内的比例值')
        folder=self.fresh('section-analysis')
        exported=self.bridge('export',folder/'source.step')
        save_snapshot(folder,exported['snapshot'])
        result=self.sdk({'action':'analyze-sections','step':str(folder/'source.step'),
                         'directory':str(folder),'reference_axis':reference_axis,'fractions':fractions})['analysis']
        result['snapshot']=exported['snapshot']
        result['include_images']=include_images
        if include_images:
            try:
                from PIL import Image
                self.bridge('capture',folder/'catia-viewport.jpg')
                with Image.open(folder/'catia-viewport.jpg') as im:im.convert('RGB').save(folder/'catia-viewport.png')
                import hashlib
                image=folder/'catia-viewport.png'
                result['images'].append(str(image))
                result['image_sha256'][image.name]=hashlib.sha256(image.read_bytes()).hexdigest()
                result['viewport_note']='当前CATIA真实视口；未改变观察方向，可能遮挡。结合截面，不据单视图确定隐藏拓扑。'
            except Exception as exc:
                result['viewport_error']=type(exc).__name__+': '+str(exc)
        save_json(folder/'analysis.json',result)
        self.log(f'截面及曲率检查已完成：{folder}；不修改或保存原CATPart')
        return result

    def list_surface_templates(self):
        from surfaces import CATALOG
        return CATALOG

    def inspect_housing(self, axis='Y'):
        if axis not in ('X','Y','Z'):raise ValueError('axis must be X/Y/Z')
        folder=self.fresh('housing-inspection')
        exported=self.bridge('export',folder/'source.step');save_snapshot(folder,exported['snapshot'])
        result=self.sdk({'action':'inspect-housing','step':str(folder/'source.step'),'axis':axis})['inventory']
        result['snapshot']=exported['snapshot'];save_json(folder/'inventory.json',result)
        return result

    def plan_housing_groove(self, operation, face_id, axis='Y', rim_coordinate=None, width=3., depth=4., center_offset=4.):
        folder=self.fresh('housing-plans')
        exported=self.bridge('export',folder/'source.step');save_snapshot(folder,exported['snapshot'])
        args=dict(step=str(folder/'source.step'),directory=str(folder),operation=operation,face_id=face_id,axis=axis,
                  rim_coordinate=rim_coordinate,width=width,depth=depth,center_offset=center_offset)
        plan=self.sdk({'action':'plan-housing-groove','arguments':args})['plan']
        plan['snapshot']=exported['snapshot']
        from housing import digest
        plan['source_code_sha256']={name:digest(ROOT/name) for name in ['housing.py','controller.py','worker.py','bin/CatiaBridge.exe']}
        save_json(folder/'plan.json',plan)
        return dict(plan=str(folder/'plan.json'),**plan,note='候选文件已校验，尚未导入CATIA；apply_housing_groove经审批才应用。')

    def housing_review(self, plan):
        from housing import digest
        path=Path(plan).resolve()
        if not path.is_relative_to(self.workspace/'housing-plans') or path.name!='plan.json':raise ValueError('方案必须来自本插件工作目录')
        value=read_json(path)
        for field in ['source','candidate','tool']:
            p=Path(value[field+'_step']).resolve()
            if p.parent!=path.parent or digest(p)!=value[field+'_sha256']:raise ValueError('方案几何已改变，请重新生成')
        exact=Path(value['candidate_brep']).resolve()
        if exact.parent!=path.parent or digest(exact)!=value['candidate_brep_sha256']:raise ValueError('BREP预演已改变，请重新生成')
        if value['source_code_sha256']!={n:digest(ROOT/n) for n in value['source_code_sha256']}:raise ValueError('建模程序已改变，请重新生成方案')
        return dict(plan=str(path),plan_sha256=digest(path),**value)

    def apply_housing_groove(self, plan, expected_sha256=None):
        from housing import digest
        review=self.housing_review(plan)
        if expected_sha256!=review['plan_sha256']:raise ValueError('方案未审批或审批后被修改')
        current=self.info()
        if current.get('path')!=review['snapshot'].get('path') or abs(current.get('volume_mm3',-1)-review['snapshot'].get('volume_mm3',-2))>.01:raise ValueError('活动壳体或体积已改变，请重新生成方案')
        folder=self.fresh('housing-revisions')
        applied=self.bridge('housing-boolean',review['tool_step'],folder/('model-'+folder.name+'.CATPart'),review['operation'])
        catia=applied['snapshot']
        actual_delta=catia.get('volume_mm3',0)-applied['before_volume_mm3']
        # Keep the prior whole-solid absolute/relative tolerance. Compare the
        # material delta in CATIA to avoid re-translating every original face.
        delta_tolerance=max(.01,abs(review['volume_after_mm3'])*1e-6)
        if abs(actual_delta-review['volume_delta_mm3'])>delta_tolerance:raise ValueError(f'CATIA原生布尔材料变化校验失败：计划={review["volume_delta_mm3"]}；实际={actual_delta}；文件保留供检查')
        self.bridge('export',folder/'model.step')
        exported=self.sdk({'action':'inspect-housing','step':str(folder/'model.step'),'axis':review['axis']})['inventory']
        if not exported['facts']['valid'] or exported['facts']['solid_count']!=1:raise ValueError('CATIA实际导出结果不是有效单实体，保留检查')
        if max(abs(a-b) for a,b in zip(exported['facts']['bounds_mm'],review['before']['bounds_mm']))>1e-4:raise ValueError('CATIA实际结果外包络改变，保留检查')
        result=dict(plan=plan,operation=review['operation'],catia=catia,volume_delta_mm3=review['volume_delta_mm3'],
                    actual_catia_volume_delta_mm3=actual_delta,delta_tolerance_mm3=delta_tolerance,catia_before_volume_mm3=applied['before_volume_mm3'],exported_facts=exported['facts'],step=str(folder/'model.step'),manifest=str(folder/'manifest.json'),limits=review['limits'],implementation=applied['implementation'])
        save_json(folder/'manifest.json',result)
        return result

    def surface_parameters(self, template, parameters=None, previous_manifest=None):
        from surfaces import validate
        if previous_manifest:
            manifest = Path(previous_manifest).resolve()
            if not manifest.is_relative_to(self.workspace/"surfaces") or manifest.name != 'manifest.json':
                raise ValueError('请选择本工作目录 surfaces 内的曲面版本')
            previous = read_json(manifest)
            if previous['template'] != template:
                raise ValueError('历史版本曲面类型不符')
            if parameters is not None and not isinstance(parameters, dict):
                raise ValueError('曲面参数须为对象')
            parameters = {**previous['parameters'], **(parameters or {})}
        return validate(template, parameters)

    def surface_family(self, manifest):
        """Resolve a managed revision lineage; never infer family from filenames."""
        path=Path(manifest).resolve();seen=set()
        for _ in range(128):
            if not path.is_relative_to(self.workspace/'surfaces') or path.name!='manifest.json' or path in seen:
                raise ValueError('曲面历史链越界或存在循环')
            seen.add(path);value=read_json(path)
            previous=value.get('previous_manifest')
            if not previous:return str(path)
            path=Path(previous).resolve()
        raise ValueError('曲面历史链过长')

    def build_surface(self, template, parameters=None, previous_manifest=None, expected_sha256=None):
        from surfaces import plan, review_sources
        token, hashes = review_sources(ROOT)
        if expected_sha256 and token != expected_sha256:
            raise ValueError('曲面程序在审阅后发生变化，请重新审阅')
        values = self.surface_parameters(template, parameters, previous_manifest)
        directory = self.fresh('surfaces')
        started = time.monotonic()
        request = plan(template, values)
        command = 'surface-build'
        if previous_manifest:
            previous = read_json(previous_manifest)
            path = Path(previous['native']['catpart']).resolve()
            if not path.is_relative_to(self.workspace/'surfaces') or not path.is_file():
                raise ValueError('历史 CATPart 不在本工作目录或已丢失')
            request['catpart'] = str(path)
            family=self.surface_family(previous_manifest)
            related=[]
            for candidate in (self.workspace/'surfaces').glob('*/manifest.json'):
                try:
                    item=read_json(candidate)
                    if 'native' in item and self.surface_family(candidate)==family:
                        related_path=Path(item['native']['catpart']).resolve()
                        if related_path.is_relative_to(self.workspace/'surfaces'):
                            related.append(str(related_path))
                except (ValueError,KeyError,OSError):
                    continue
            request['related_catparts']=related
            command = 'surface-revise'
        save_json(directory/'request.json', request)
        source = directory/'source'
        source.mkdir()
        for name in ['surfaces.py','style_surfaces.py','surface_quality.py','bridge/SurfaceBuilder.cs','bridge/StyleSurfaceBuilder.cs','bridge/CatiaBridge.cs','bin/CatiaBridge.exe']:
            target = source/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,target)
        if self.cancel.is_set(): raise RuntimeError('任务已中止')
        try:
            native = self.bridge(command, directory/'request.json', directory/'result')
        except Exception as exc:
            save_json(directory/'manifest.json', {'version':'0.4.0','template':template,'parameters':values,
                      'ok':False,'stage':'native-build','error':str(exc),'source_sha256':hashes,
                      'class_a_accepted':False,'elapsed_seconds':round(time.monotonic()-started,3)})
            raise
        manifest = {'version':'0.4.0', 'template':template, 'parameters':values, 'native':native,
                    'previous_manifest':str(previous_manifest) if previous_manifest else None,
                    'source_sha256':hashes,'class_a_accepted':False,'manifest':str(directory/'manifest.json')}
        # Preserve native results even if independent inspection fails or is cancelled.
        save_json(directory/'manifest.json',manifest)
        try:
            quality = self.sdk({'action':'inspect-surface','output':str(directory/'result'),'offset':values['OffsetDistance'],'template':template,'parameters':values})['quality']
        except Exception as exc:
            manifest.update(ok=False,stage='independent-inspection',error=str(exc),elapsed_seconds=round(time.monotonic()-started,3))
            save_json(directory/'manifest.json',manifest)
            raise
        manifest.update(quality=quality,elapsed_seconds=round(time.monotonic()-started,3),ok=quality['operations_passed'])
        save_json(directory/'manifest.json',manifest)
        if not quality['operations_passed']:
            raise ValueError('曲面独立检查未通过，文件及报告已保留：'+str(directory/'manifest.json'))
        self.log(f"曲面操作完成：{native['catpart']}；仅为演示，非A级验收")
        return manifest

    def inspect_surface(self, manifest):
        path = Path(manifest).resolve()
        if not path.is_relative_to(self.workspace/'surfaces') or path.name != 'manifest.json':
            raise ValueError('仅检查本工作目录管理的曲面版本')
        result=read_json(path)
        output=Path(result['native']['catpart']).parent.resolve()
        if not output.is_relative_to(self.workspace/'surfaces'):
            raise ValueError('曲面路径超出工作目录')
        return self.sdk({'action':'inspect-surface','output':str(output),'offset':result['parameters']['OffsetDistance'],'template':result['template'],'parameters':result['parameters']})

    def list_automotive_templates(self):
        from automotive import CATALOG
        return CATALOG

    def automotive_parameters(self, template, parameters=None, previous_manifest=None):
        from automotive import validate
        if previous_manifest:
            manifest = Path(previous_manifest).resolve()
            if not manifest.is_relative_to(self.workspace/"revisions") or manifest.name != "manifest.json":
                raise ValueError("只能重建本工作目录内的汽车模板版本")
            previous = read_json(manifest)
            if previous["template"] != template:
                raise ValueError("历史版本与当前模板类型不符")
            parameters = {**previous["parameters"], **(parameters or {})}
        return validate(template, parameters)

    def build_automotive(self, template, parameters=None, previous_manifest=None, expected_sha256=None):
        from automotive import CATALOG
        started = time.monotonic()
        values = self.automotive_parameters(template, parameters, previous_manifest)
        result = self.run_model(ROOT/"samples"/CATALOG[template]["notebook"], values, expected_sha256=expected_sha256)
        result.update(template=template, parameters=values, manifest=str(Path(result["output"])/"manifest.json"),
                      previous_manifest=str(previous_manifest) if previous_manifest else None,
                      elapsed_seconds=round(time.monotonic()-started, 3),
                      acceptance={"customer_sample_accepted": False, "parameter_completeness_95_verified": False,
                                  "global_deviation_005_verified": False, "class_a_verified": False},
                      note="SDK 参数演示模板；CATIA 中为 STEP 导入实体。尚未按客户图纸验收。")
        save_json(Path(result["output"])/"manifest.json", result)
        self.log(f"汽车演示模型已生成：{result['catia']['path']}；耗时 {result['elapsed_seconds']} 秒")
        return result

    def export(self):
        folder = self.fresh("exports")
        result = self.bridge("export", folder/"source.step")
        save_snapshot(folder, result["snapshot"])
        self.log(f"已导出 CATIA 快照与 STEP：{folder}")
        return result

    def prepare_seal(self):
        folder = self.fresh("features")
        result = self.bridge("export", folder/"source.step")
        save_snapshot(folder, result["snapshot"])
        base = self.sdk({"action": "prepare", "step": str(folder/"source.step"), "directory": str(folder)})["base"]
        feature = write_seal(folder, base)
        feature["original_snapshot"] = result["snapshot"]
        save_json(folder/"feature.json", feature)
        self.log(f"已保存基础实体并创建密封槽 notebook：{feature['notebook']}")
        return feature

    def run_model(self, notebook, overrides=None, import_to_catia=True, expected_sha256=None):
        notebook = Path(notebook).resolve()
        if not notebook.is_file():
            raise FileNotFoundError(notebook)
        feature_path = notebook.parent/"feature.json"
        if feature_path.exists():
            saved_feature = read_json(feature_path)
            overrides = {**saved_feature.get("overrides", {}), **(overrides or {})}
        # Preserve the complete notebook workspace, including local modules and
        # hash-pinned inputs, so later edits cannot change the recorded revision.
        revision = self.fresh("revisions")
        snapshot = revision/"source"
        if self.workspace == notebook.parent or self.workspace.is_relative_to(notebook.parent):
            raise ValueError("请选择独立的模型子文件夹；模型目录不能包含插件工作目录")
        shutil.copytree(notebook.parent, snapshot, ignore=shutil.ignore_patterns(
            "__marimo__", ".sca-editor", "__pycache__", ".git", "*.CATPart", "*.CATProduct"))
        import hashlib
        if expected_sha256 and hashlib.sha256((snapshot/notebook.name).read_bytes()).hexdigest() != expected_sha256:
            raise ValueError("源代码在审阅后发生了变化，请重新查看并执行")
        result = self.sdk({"action": "run", "notebook": str(snapshot/notebook.name),
                           "output": str(revision/"result"), "overrides": overrides or {}})
        result["original_notebook"] = str(notebook)
        self.log(f"SDK 建模通过：{result['facts']['volume_mm3']:.6f} mm³，{result['facts']['face_count']} 个面")
        if import_to_catia:
            if self.cancel.is_set():
                raise RuntimeError("任务已中止；SDK 文件已保留，未导入 CATIA")
            result["catia"] = self.import_result(result["step"], revision/"result"/"model.CATPart", result["facts"]["volume_mm3"])
        save_json(revision/"result"/"manifest.json", result)
        if feature_path.exists():
            feature = read_json(feature_path)
            feature.update(active=True, revision=feature.get("revision", 0)+1, last_result=result, overrides=overrides or {})
            save_json(feature_path, feature)
        return result

    def import_result(self, step, destination, expected=None):
        result = self.bridge("import", step, destination)
        if expected is not None:
            actual = result.get("volume_mm3")
            if actual is None or abs(actual-expected) > max(.01, abs(expected)*1e-6):
                raise ValueError(f"CATIA 体积验证失败：SDK={expected}；CATIA={actual}。导入文件已保留供检查")
        self.log(f"已打开 CATIA 新零件：{destination}")
        return result

    def remove_seal(self, notebook):
        feature_path = Path(notebook).resolve().parent/"feature.json"
        feature = read_json(feature_path)
        base = feature_path.parent/"source.step"
        if not base.is_file():
            raise FileNotFoundError("基础 STEP 缺失；请恢复 feature 工作目录")
        folder = self.fresh("restored")
        result = self.import_result(base, folder/"base-restored.CATPart", feature.get("original_snapshot", {}).get("volume_mm3"))
        feature.update(active=False, restored_document=result)
        save_json(feature_path, feature)
        return result

    def write_notebook(self, name, source):
        import ast
        if not isinstance(source, str) or "[tool.simplecadapi]" not in source:
            raise ValueError("必须包含 SimpleCADAPI notebook 头")
        ast.parse(source)
        name = Path(name).name
        if not name.endswith(".py"):
            raise ValueError("notebook 文件名必须为 .py")
        folder = self.fresh("models")
        path = folder/name
        path.write_text(source, encoding="utf-8")
        return {"notebook": str(path), "note": "已保存代码；运行前请查看完整源代码"}

    def editor(self, path):
        import socket
        from importlib.util import find_spec
        if find_spec("simplecadapi.editor") is None:
            raise RuntimeError("SimpleCADAPI editor 未安装")
        port = None
        for number in range(7190, 7210):
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", number))
                    port = number
                    break
                except OSError:
                    pass
        if port is None:
            raise RuntimeError("编辑器端口 7190–7209 已占用")
        folder = self.fresh("editor-logs")
        cli = Path(sys.executable).parent/"Scripts"/"sca.exe"
        if not cli.exists():
            cli = Path(os.environ["APPDATA"])/"Python"/f"Python{sys.version_info.major}{sys.version_info.minor}"/"Scripts"/"sca.exe"
        with (folder/"stdout.log").open("w", encoding="utf-8") as stdout, (folder/"stderr.log").open("w", encoding="utf-8") as stderr:
            child = subprocess.Popen([str(cli), "edit", str(path), "--port", str(port)], stdout=stdout, stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        self.log(f"编辑器启动中：http://127.0.0.1:{port}；日志：{folder}；PID {child.pid}")
        return {"url": f"http://127.0.0.1:{port}", "pid": child.pid, "logs": str(folder)}
