"""Loopback-only WebUI, per-process authentication, no generic OpenCode proxy."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import urlparse
import webbrowser
from web_backend import WebBackend

ROOT = Path(__file__).resolve().parent


def create_server(backend, port=0, token=None):
    token = token or secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def authorized(self):
            expected_host = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != expected_host: return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected_host: return False
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith('/api/'):
                if not self.authorized(): return self.reply({'error': 'Unauthorized'}, 401)
                try:
                    if path == '/api/state': return self.reply(backend.state())
                    if path.startswith('/api/jobs/'): return self.reply(backend.job(path.split('/')[-1]))
                    return self.reply({'error': 'Not found'}, 404)
                except (ValueError, KeyError) as error: return self.reply({'error': str(error)}, 400)
            mapping = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
            if path not in mapping: return self.reply({'error': 'Not found'}, 404)
            raw = (ROOT / 'webui' / mapping[path]).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', (mimetypes.guess_type(mapping[path])[0] or 'text/plain') + '; charset=utf-8')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_POST(self):
            if not self.authorized(): return self.reply({'error': 'Unauthorized'}, 401)
            try:
                count = int(self.headers.get('Content-Length', '0'))
                if count <= 0 or count > 24*1024*1024: return self.reply({'error': 'Invalid body size'}, 413)
                body = json.loads(self.rfile.read(count))
                route = urlparse(self.path).path
                if route == '/api/connect': result = backend.connect()
                elif route == '/api/new': result = backend.new(body.get('model'), body.get('agent'))
                elif route == '/api/select': result = backend.select(body['session'])
                elif route == '/api/refresh': result = backend.refresh()
                elif route == '/api/send': result = backend.send(body['operation_id'], body.get('text', ''), body.get('files', []), body.get('model'), body.get('agent'))
                elif route == '/api/interrupt': result = backend.interrupt()
                elif route == '/api/stop-waiting': result = backend.stop_waiting()
                elif route == '/api/full':
                    with backend.guard:
                        if not backend.link.session: backend.new()
                        result = {'pid': backend.link.open_full_interface()}
                else: return self.reply({'error': 'Not found'}, 404)
                self.reply(result)
            except (ValueError, KeyError, TypeError) as error: self.reply({'error': str(error)}, 400)
            except Exception as error:
                # Avoid exposing provider/server bodies or auth values to browsers.
                self.reply({'error': type(error).__name__ + '；请刷新同一会话核对，未自动重发'}, 500)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server, token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--descriptor-stdout', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')) if (ROOT / 'config.json').exists() else {}
    workspace = args.workspace or Path(config.get('workspace', str(Path.home() / 'Documents/PhyXiCATIAAgent')))
    backend = WebBackend(workspace, args.project or config.get('opencode_project'))
    server, token = create_server(backend, args.port)
    url = 'http://127.0.0.1:' + str(server.server_port)
    if args.descriptor_stdout: print(json.dumps({'url': url, 'token': token}), flush=True)
    else: print('PhyXi WebUI: ' + url + ' (authenticated browser opens automatically)', flush=True)
    if args.browser: webbrowser.open(url + '/#token=' + token)
    if args.descriptor_stdout:
        # Electron closing the input pipe ends only this observer, never OpenCode/CATIA.
        import sys
        def parent_watch():
            for line in sys.stdin:
                if line.strip() == 'shutdown': break
            backend.cancel.set(); server.shutdown()
        threading.Thread(target=parent_watch, daemon=True).start()
    try: server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt: backend.cancel.set()
    finally: server.server_close()


if __name__ == '__main__': main()
