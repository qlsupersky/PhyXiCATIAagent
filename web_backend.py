"""Local WebUI application service. OpenCode retains all model/tool capabilities."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from PIL import Image
from opencode_link import OpenCodeLink, read_attachment


def present(rows):
    """Strip persisted binary payloads; keep structured feedback and real tools."""
    messages, tools = [], []
    for row in reversed(rows):
        if row.get('type') == 'user':
            messages.append({'id': row['id'], 'role': 'user', 'text': row.get('text', ''),
                             'files': [f.get('name', 'attachment') for f in row.get('files', [])]})
        elif row.get('type') == 'assistant':
            text = '\n'.join(p.get('text', '') for p in row.get('content', []) if p.get('type') == 'text')
            if text: messages.append({'id': row['id'], 'role': 'assistant', 'text': text})
            for part in row.get('content', []):
                if part.get('type') != 'tool': continue
                state = part.get('state', {})
                text = '\n'.join(p.get('text', '') for p in state.get('content', []) if p.get('type') == 'text')
                text = text or state.get('output', '') or state.get('error', '')
                feedback = None
                if isinstance(text, str):
                    try: feedback = json.loads(text)
                    except ValueError: pass
                calls = state.get('metadata', {}).get('toolCalls', [])
                tools.append({'id': part.get('id', row['id']), 'name': ', '.join(c.get('tool', '') for c in calls) or part.get('name', 'tool'),
                              'status': state.get('status', ''), 'text': str(text), 'feedback': feedback})
    return {'messages': messages, 'tools': tools}


class WebBackend:
    def __init__(self, workspace, project=None, link=None):
        self.workspace = Path(workspace).resolve()
        # Web frontend has its own current-session pointer; actual sessions are shared.
        self.link = link or OpenCodeLink(self.workspace, project)
        if link is None:
            self.link.state_file = self.link.history / 'web-current-session.json'
            self.link.session = None
            if self.link.state_file.exists():
                state = json.loads(self.link.state_file.read_text(encoding='utf-8'))
                if state.get('project') == str(self.link.project): self.link.session = state.get('session')
        self.folder = self.workspace / 'web-jobs'; self.folder.mkdir(parents=True, exist_ok=True)
        self.guard = threading.RLock()
        self.active = None
        self.cancel = threading.Event()
        self.view = {'messages': [], 'tools': []}
        self.catalog = {'models': [], 'agents': [], 'commands': []}
        self.mcp = []

    def ensure_free(self):
        if self.active: raise ValueError('本轮仍在处理，请等待或刷新原会话')

    def connect(self):
        with self.guard:
            self.ensure_free()
            status = self.link.connect()
            self.catalog = self.link.catalog(); self.mcp = status['mcp']['data']
            if self.link.session: self.view = present(self.link.refresh()['messages'])
            return self.state(include_sessions=True)

    def state(self, include_sessions=False):
        with self.guard:
            return {'version': '0.7.0', 'project': str(self.link.project), 'workspace': str(self.workspace),
                    'session': self.link.session, 'active': self.active, 'connected': bool(self.link.url),
                    'mcp': self.mcp, 'catalog': self.catalog, 'plans': self.plan_progress(), **self.view,
                    **({'sessions': self.link.sessions()} if include_sessions and self.link.url else {})}

    def plan_progress(self):
        """Observe the local shared plan journal while a remote MCP call is running."""
        path = self.workspace / 'tool-plans/plans.sqlite'
        if not path.exists(): return []
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        try:
            rows = db.execute('SELECT record FROM plans ORDER BY rowid DESC LIMIT 3').fetchall()
            plans = []
            for row in rows:
                record = json.loads(row[0])
                plans.append({k:record.get(k) for k in ('request_id','status','completion','events','skipped_steps','declared_checks_passed')}
                             | {'results': [{k:r.get(k) for k in ('step','tool','ok','code','duration_ms','verification','completion')} for r in record['results']]})
            return plans
        finally: db.close()

    def new(self, model=None, agent=None):
        with self.guard:
            self.ensure_free()
            if not self.link.url: self.link.connect()
            self.link.new_session(model=model, agent=agent); self.view = present([])
            return self.state(True)

    def select(self, sid):
        with self.guard:
            self.ensure_free(); self.link.select_session(sid)
            self.view = present(self.link.refresh()['messages'])
            return self.state(True)

    def refresh(self):
        with self.guard:
            self.ensure_free()
            result = self.link.refresh(); self.view = present(result['messages'])
            self.reconcile_jobs(result)
            return {**self.state(True), 'pending': result['pending']}

    def reconcile_jobs(self, refreshed):
        # Only exact OpenCode terminal evidence settles an interrupted local observer.
        for path in self.folder.glob('*.json'):
            job = json.loads(path.read_text(encoding='utf-8'))
            result = refreshed.get('completed')
            if not result and job.get('evidence_folder'):
                evidence = Path(job['evidence_folder']) / 'result.json'
                if evidence.is_file(): result = json.loads(evidence.read_text(encoding='utf-8'))
            if not result or result.get('session') != self.link.session: continue
            if job.get('session') == self.link.session and job.get('message_id') == result['message_id']:
                job.update(status=str(result['outcome']).upper(), completion='KNOWN_FINISHED', updated_at=time.time())
                OpenCodeLink._write(path, job)

    def attachments(self, files):
        if not isinstance(files, list) or len(files) > 12: raise ValueError('每轮最多12个附件')
        result = []; total = 0
        for item in files:
            name = item['name']
            if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or len(name) > 128:
                raise ValueError('附件名无效')
            raw = base64.b64decode(item['data'], validate=True); total += len(raw)
            if len(raw) > 8*1024*1024 or total > 16*1024*1024: raise ValueError('单文件最多8MiB，每轮附件合计16MiB')
            folder = self.folder / 'attachments' / uuid.uuid4().hex; folder.mkdir(parents=True)
            path = folder / name; path.write_bytes(raw)
            result.append(read_attachment(path))
        return result

    def job(self, operation_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', operation_id): raise ValueError('Invalid operation_id')
        path = self.folder / (operation_id + '.json')
        with self.guard:
            if not path.exists(): return {'status': 'NOT_FOUND', 'operation_id': operation_id}
            job = json.loads(path.read_text(encoding='utf-8'))
            if job['status'] == 'RUNNING' and self.active != operation_id:
                job.update(status='NEEDS_REFRESH', completion='UNCERTAIN')
            return job

    def send(self, operation_id, text, files=(), model=None, agent=None):
        if not isinstance(text, str) or len(text) > 100000 or not text.strip() and not files: raise ValueError('请输入消息或添加附件')
        self.job(operation_id)  # validate before using as a path
        digest = hashlib.sha256(json.dumps({'text': text, 'files': files, 'model': model, 'agent': agent}, sort_keys=True).encode()).hexdigest()
        path = self.folder / (operation_id + '.json')
        with self.guard:
            if path.exists():
                job = self.job(operation_id)
                if job['digest'] != digest: raise ValueError('operation_id 已用于不同内容')
                return {**job, 'cached_no_resubmit': True}
            self.ensure_free()
            if not self.link.url: raise ValueError('请先连接 OpenCode')
            self.link._ensure_idle()
            attachments = self.attachments(list(files))
            if not self.link.session: self.link.new_session(model=model, agent=agent)
            else: self.link.switch(model, agent)
            job = {'operation_id': operation_id, 'digest': digest, 'status': 'RUNNING', 'completion': 'UNCERTAIN',
                   'session': self.link.session, 'created_at': time.time(), 'automatic_retry_allowed': False}
            with path.open('x', encoding='utf-8') as out: json.dump(job, out)
            self.active = operation_id; self.cancel.clear()
        def observe(rows):
            view = present(rows)
            with self.guard:
                self.view = view
                pending = self.link._pending()
                if pending.exists():
                    receipt = json.loads(pending.read_text(encoding='utf-8'))
                    job['message_id'] = receipt['message_id']
                    if receipt.get('folder'): job['evidence_folder'] = receipt['folder']
                OpenCodeLink._write(path, job)
        def work():
            try:
                result = self.link.send(text, attachments, cancel=self.cancel, observe=observe)
                with self.guard: self.view = present(result['messages'])
                job.update(status=str(result['outcome']).upper(), completion='KNOWN_FINISHED', message_id=result['message_id'],
                           attachments_verified=result['attachments_verified'])
            except Exception as error:
                pending = self.link._pending()
                if pending.exists():
                    receipt = json.loads(pending.read_text(encoding='utf-8'))
                    job['message_id'] = receipt['message_id']
                    if receipt.get('folder'): job['evidence_folder'] = receipt['folder']
                job.update(status='NEEDS_REFRESH' if pending.exists() else 'FAILED', completion='UNCERTAIN' if pending.exists() else 'NOT_DISPATCHED',
                           message=str(error))
            finally:
                with self.guard:
                    job['updated_at'] = time.time(); OpenCodeLink._write(path, job)
                    self.active = None
        threading.Thread(target=work, daemon=True).start()
        return job

    def interrupt(self):
        self.link.interrupt()
        return {'requested': True, 'CAD_rollback': False, 'message': '已向 OpenCode 请求中止；已派发的 CATIA 调用仍需实际完成证据'}

    def stop_waiting(self):
        self.cancel.set()
        return {'waiting_stopped': True, 'backend_interrupted': False}
