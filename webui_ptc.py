"""Existing WebUI with a dedicated GLM/OpenCode project and PTC MCP profile.

No model credentials are written to the project. Does not replace global settings.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import tomllib
import urllib.request
import webbrowser
from opencode_link import OpenCodeLink, cli_path
from web_backend import WebBackend
from web_server import create_server


def profile(base_url, python, server, backends, node):
    return {
        'providers': {'phyxi-glm': {
            'name': 'GLM WebUI PTC', 'package': '@opencode/ai/providers/openai-compatible',
            'settings': {'baseURL': base_url, 'apiKey': '{env:PHYXI_GLM_API_KEY}'},
            'models': {'glm-5.3-flash': {
                'modelID': 'glm-5.3-flash', 'name': 'GLM-5.3-Flash / PTC',
                'capabilities': {'tools': True, 'input': ['text', 'image'], 'output': ['text']},
                'limit': {'context': 128000, 'output': 16384}, 'settings': {'store': False}}}}},
        'model': 'phyxi-glm/glm-5.3-flash',
        'mcp': {
            'catia-code': {'type': 'local', 'command': [str(python), str(server)],
                'environment': {'PHYXI_PTC_BACKENDS': str(backends), 'PHYXI_PTC_NODE': str(node)},
                'enabled': True}},
        'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]}


def credential(provider):
    key = os.environ.get('PHYXI_GLM_API_KEY')
    base = os.environ.get('PHYXI_GLM_BASE_URL')
    if key and base: return base.rstrip('/'), key
    dbpath = Path.home()/'.cc-switch/cc-switch.db'
    with sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute("select settings_config from providers where id=? and app_type='codex'", (provider,)).fetchone()
    if not row: raise RuntimeError('GLM provider not found. Set PHYXI_GLM_BASE_URL and PHYXI_GLM_API_KEY locally.')
    config = json.loads(row[0]); c = tomllib.loads(config['config'])
    return c['model_providers'][c['model_provider']]['base_url'].rstrip('/'), config['auth']['OPENAI_API_KEY']


def connect_ptc(link, config):
    states=link.api('GET','/api/mcp')['data']
    status={row['name']:row['status'].get('status') for row in states}
    if status.get('catia-code')=='failed':
        raise RuntimeError('PTC connection failed. Inspect the original task state; no automatic reconnect.')
    if status.get('catia-code')!='connected':
        link.api('PUT','/api/experimental/mcp/catia-code',{'config':config},timeout=60)
    for name in ('native-modeling','catia-v5'):
        if name in status:
            link.api('DELETE','/api/experimental/mcp/'+name,timeout=20)
    return link.api('GET','/api/mcp')


RULES = '''# WebUI GLM Code Mode
For CATIA always write JavaScript orchestration and submit via catia-code ptc_execute.
Discover exact schemas with ptc_catalog. No direct CAD MCP, shell or COM for CAD.
Methods return {ok,data,uncertain,images}. Inspect actual shapes, do not guess.
Check tools.native_modeling.modeling_status({}).data.gate.status is IDLE first.
Use immutable request IDs. Poll RUNNING same ID, never replay writes.
Keep final return <=8192 bytes. Filter parameters locally. Part features are in bodies[].features.
SaveAs a new copy before editing. Verify exact active file path. Preserve unrelated documents.
Save current named file with {}. Use explicit units and tolerances, cad.near needs abs and rel.
On failure/uncertainty stop changes, preserve evidence. A successful program is not geometry acceptance.
Show actual generated JS and measured results in the conversation. Do not invent validation.
'''


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--workspace', type=Path, required=True)
    ap.add_argument('--server', type=Path, required=True)
    ap.add_argument('--backends', type=Path, required=True)
    ap.add_argument('--node', type=Path, required=True)
    ap.add_argument('--ccswitch-provider', default='phyxi-catia-micu-glm-5-3-flash')
    args=ap.parse_args(); project=args.project.resolve(); project.mkdir(parents=True,exist_ok=True)
    descriptor=project/'webui-instance.private.json'
    if descriptor.exists():
        old=json.loads(descriptor.read_text(encoding='utf8'))
        try:
            req=urllib.request.Request(old['url']+'/api/state',headers={'Authorization':'Bearer '+old['token']})
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req,timeout=3) as response: state=json.load(response)
            if Path(state['project']).resolve()==project:
                webbrowser.open(old['url']+'/#token='+old['token']); return
        except (OSError,ValueError,KeyError): pass
    base,key=credential(args.ccswitch_provider)
    cfg=profile(base,os.sys.executable,args.server,args.backends,args.node)
    (project/'opencode.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
    (project/'AGENTS.md').write_text(RULES,encoding='utf8')
    password=secrets.token_urlsafe(32)
    with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env=os.environ.copy();env['PHYXI_GLM_API_KEY']=key;env['OPENCODE_SERVER_PASSWORD']=password
    # Dedicated config root prevents inherited global MCP registrations from
    # entering the model's tool catalog. Does not change the user's global file.
    private_config=project/'config-home';private_config.mkdir(exist_ok=True)
    env['XDG_CONFIG_HOME']=str(private_config)
    process=subprocess.Popen([str(cli_path()),'serve','--hostname','127.0.0.1','--port',str(port)],
        cwd=project,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
    def logs():
        for raw in iter(process.stdout.readline,b''):
            line=raw.decode('utf8',errors='replace').replace(key,'[REDACTED]').replace(password,'[REDACTED]')
            with (project/'service.private.log').open('a',encoding='utf8') as f:f.write(line)
    threading.Thread(target=logs,daemon=True).start()
    class Link(OpenCodeLink):
        def connect(self):
            self.url='http://127.0.0.1:'+str(port)
            self.authorization='Basic '+base64.b64encode(('opencode:'+password).encode()).decode()
            # This OpenCode build normalizes away enabled/disabled config fields.
            # Explicitly register PTC and remove legacy direct registrations in
            # this dedicated service before any model prompt can be submitted.
            return {'base_url':self.url,'mcp':connect_ptc(self,cfg['mcp']['catia-code']),'session':self.session}
    link=Link(args.workspace,project);link.state_file=project/'web-current-session.json';link.session=None
    if link.state_file.exists():
        saved=json.loads(link.state_file.read_text(encoding='utf8'))
        if Path(saved.get('project','')).resolve()==project:link.session=saved.get('session')
    deadline=time.monotonic()+90
    while True:
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=1):break
        except OSError:
            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('OpenCode service unavailable. Inspect local service.private.log.')
            time.sleep(.3)
    backend=WebBackend(args.workspace,project,link=link)
    web,token=create_server(backend)
    url='http://127.0.0.1:'+str(web.server_port)
    descriptor.write_text(json.dumps({'url':url,'token':token,'pid':os.getpid()},indent=2),encoding='utf8')
    webbrowser.open(url+'/#token='+token)
    print('WebUI ready: GLM-5.3-Flash + Code Mode. Keep this process running.',flush=True)
    web.serve_forever()


if __name__=='__main__': main()
