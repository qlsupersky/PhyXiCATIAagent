"""Verify real Codex app-server MCP calls without a model turn or CAD dispatch.

Pass the actual Codex executable with --codex. Requires the app-server protocol
available in Codex CLI 0.162.1. Output is a compact summary, not raw sessions.
"""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time


def verify(executable, cwd):
    messages = queue.Queue()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(executable), 'app-server', '--stdio'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def read():
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
            messages.put({'closed': True})

        threading.Thread(target=read, daemon=True).start()
        counter = 0

        def request(method, params):
            nonlocal counter
            counter += 1
            process.stdin.write(json.dumps({'id': counter, 'method': method, 'params': params}) + '\n')
            process.stdin.flush()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                item = messages.get(timeout=max(.01, deadline - time.monotonic()))
                if item.get('closed'):
                    raise RuntimeError('Private Codex app-server closed unexpectedly')
                if item.get('id') == counter:
                    if 'error' in item:
                        raise RuntimeError('Codex rejected method: ' + method)
                    return item['result']
            raise TimeoutError(method)

        try:
            request('initialize', {'clientInfo': {'name': 'phyxi-connection-check', 'version': '0.1.0'},
                'capabilities': {'experimentalApi': True}})
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            thread = request('thread/start', {'cwd': str(Path(cwd).resolve()), 'ephemeral': True})['thread']['id']
            status = request('mcpServerStatus/list', {'threadId': thread, 'detail': 'full', 'limit': 100})
            counts = {x['name']: len(x.get('tools', {})) for x in status['data']}
            for name in ('native-modeling', 'catia-v5'):
                if not counts.get(name):
                    raise RuntimeError('MCP did not expose tools: ' + name)

            def tool(server, name):
                result = request('mcpServer/tool/call', {'threadId': thread, 'server': server,
                    'tool': name, 'arguments': {}})
                if result.get('isError'):
                    raise RuntimeError('Read-only MCP tool failed: ' + name)
                return json.loads(next(x['text'] for x in result['content'] if x['type'] == 'text'))

            native = tool('native-modeling', 'modeling_status')
            catalog = tool('catia-v5', 'catia_plan_catalog')
            skills = request('skills/list', {'cwds': [str(Path(cwd).resolve())], 'forceReload': True})
            found = [x['name'] for group in skills['data'] for x in group['skills']
                if x['name'].split(':')[-1] == 'catia-native' and x.get('enabled')]
            return {'connected': True, 'tool_counts': {n: counts[n] for n in ('native-modeling', 'catia-v5')},
                'gate_status': native['gate']['status'], 'adapter_version': catalog['adapter']['version'],
                'enabled_skills': found, 'model_turn_submitted': False, 'CAD_dispatch': False}
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                # Only the child we own; never terminate CATIA or desktop Codex.
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True, type=Path)
    parser.add_argument('--cwd', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = verify(args.codex, args.cwd)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding='utf-8')
    print(text)
