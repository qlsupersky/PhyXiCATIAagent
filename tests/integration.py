"""Real CATIA/SDK integration check. Creates new test documents; needs CATIA running.
Usage: python tests/integration.py --workspace <new validation folder>
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
sys.stdout.reconfigure(encoding="utf-8")
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import Controller, ROOT, read_json, save_json
from agent import Agent


def agent_check(controller):
    payloads = []
    emitted = []
    rejected = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payloads.append(request)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if len(payloads) == 1:
                chunks = [{"tool_calls": [{"index": 0, "id": "read1", "function": {"name": "inspect_", "arguments": "{"}}]},
                          {"tool_calls": [{"index": 0, "function": {"name": "catia", "arguments": "}"}}]},
                          {"tool_calls": [{"index": 1, "id": "write1", "function": {"name": "write_notebook", "arguments": json.dumps({"name": "rejected.py", "source": "# [tool.simplecadapi]\nraise RuntimeError('must not execute')\n"})}}]}]
            else:
                chunks = [{"content": "读取完成，"}, {"content": "写入被用户拒绝。"}]
            for chunk in chunks:
                self.wfile.write(("data: "+json.dumps({"choices": [{"delta": chunk}]})+"\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def reject(name, args):
        rejected.append(name)
        return False
    agent = Agent(controller, emitted.append, reject, lambda: str(ROOT/"samples"/"plate.py"))
    try:
        from providers import PROVIDERS
        agent.send("读取 CATIA 并提议一次写入", f"http://127.0.0.1:{server.server_port}/v1", "test-only", "glm-mock", {}, provider=PROVIDERS[1])
        assert len(payloads) == 2
        tools = [m for m in payloads[1]["messages"] if m["role"] == "tool"]
        assert json.loads(tools[0]["content"])["ok"] is True
        assert json.loads(tools[1]["content"])["ok"] is False
        assert rejected == ["write_notebook"]
        assert not list(controller.workspace.rglob("rejected.py"))
        assert "读取完成，写入被用户拒绝。" in "".join(emitted)
        return {"ok": True, "kind": "localhost simulated SSE and tools", "requests": len(payloads),
                "rejected_write_not_executed": True, "external_llm_tested": False}
    finally:
        server.shutdown()
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=False)
    controller = Controller(args.workspace)
    report = {"checks": []}
    def record(label, **facts):
        report["checks"].append({"name": label, "ok": True, **facts})
        save_json(args.workspace/"validation.json", report)
        print("PASS", label, flush=True)
    plate = controller.run_model(ROOT/"samples"/"plate.py", {"hole_diameter": 12})
    analytical = 120*90*20-math.pi*6**2*20
    assert abs(plate["facts"]["volume_mm3"]-analytical) < .001
    record("parameterized-plate-CATIA-import", sdk_volume=plate["facts"]["volume_mm3"],
           catia_volume=plate["catia"]["volume_mm3"], expected_volume=analytical, catpart=plate["catia"]["path"])
    controller.bridge("create-test", args.workspace/"test-base.CATPart")
    feature = controller.prepare_seal()
    base_path = Path(feature["base"]["brep"])
    base_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
    first = controller.run_model(feature["notebook"])
    assert first["facts"]["solid_count"] == 1 and first["facts"]["face_count"] == 40
    record("seal-create-from-CATIA-base", sdk_volume=first["facts"]["volume_mm3"],
           catia_volume=first["catia"]["volume_mm3"], catpart=first["catia"]["path"])
    revised = controller.run_model(feature["notebook"], {"Depth": 3, "TopWidth": 3.4, "FloorRadius": .4})
    assert abs(first["facts"]["volume_mm3"]-revised["facts"]["volume_mm3"]) > 1
    assert hashlib.sha256(base_path.read_bytes()).hexdigest() == base_hash
    assert Path(first["catia"]["path"]).is_file()
    record("seal-parameter-edit-rebuild", sdk_volume=revised["facts"]["volume_mm3"],
           catia_volume=revised["catia"]["volume_mm3"], immutable_base=True, earlier_revision_preserved=True,
           catpart=revised["catia"]["path"])
    before = controller.info()["path"]
    try:
        controller.run_model(feature["notebook"], {"Depth": -1})
        raise AssertionError("Invalid dimensions were accepted")
    except RuntimeError as exc:
        assert "Groove dimensions must be positive" in str(exc), str(exc)
    assert controller.info()["path"] == before
    record("invalid-geometry-blocked-before-CATIA-import", active_document_unchanged=True)
    try:
        controller.run_model(ROOT/"samples"/"plate.py", {"misspelled_parameter": 1})
        raise AssertionError("Unknown parameter accepted")
    except RuntimeError as exc:
        assert "Unknown named SDK parameter" in str(exc)
    record("unknown-parameter-rejected")
    restored = controller.remove_seal(feature["notebook"])
    assert abs(restored["volume_mm3"]-216000) < .001
    assert read_json(Path(feature["notebook"]).parent/"feature.json")["active"] is False
    record("seal-delete-restores-preserved-base", volume=restored["volume_mm3"], catpart=restored["path"])
    record("agent-SSE-tool-approval", **agent_check(controller))
    report["ok"] = True
    report["environment"] = {"catia": "V5-6R2023 SP4 B33", "sdk": "2.2.1", "python": sys.version}
    save_json(args.workspace/"validation.json", report)


if __name__ == "__main__":
    main()
