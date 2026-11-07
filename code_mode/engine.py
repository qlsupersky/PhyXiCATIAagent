"""Durable program orchestration. Guest code never runs inside this Python host."""
import asyncio
from contextlib import AsyncExitStack, contextmanager
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVERS = ('native-modeling', 'catia-v5')
ALIASES = {'native_modeling': 'native-modeling', 'catia_v5': 'catia-v5'}
TERMINAL = ('SUCCEEDED', 'FAILED', 'REJECTED')


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def decode_text(value):
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            break
    return value


def project(raw):
    """Data available to guest; full MCP envelope remains in local evidence."""
    data = raw.get('structuredContent')
    if data is None:
        data = decode_text('\n'.join(c.get('text', '') for c in raw.get('content', []) if c.get('type') == 'text'))
    ok = not raw.get('isError', False)
    uncertain = False
    if isinstance(data, dict):
        ok = ok and data.get('ok', True) is not False
        state = data.get('state', data.get('status'))
        ok = ok and state not in ('FAILED', 'FROZEN', 'UNCERTAIN', 'REJECTED_BUSY')
        uncertain = data.get('completion') == 'UNCERTAIN' or state in ('FROZEN', 'UNCERTAIN')
        plan = data.get('plan')
        if isinstance(plan, dict):
            uncertain = uncertain or plan.get('completion') == 'UNCERTAIN'
            ok = ok and plan.get('status') == 'SUCCEEDED'
            if len(plan.get('results', [])) == 1 and not plan['steps'][0]['tool'].startswith('catia_plan_'):
                data = plan['results'][0]['data']
        # Older native failure responses may omit state but carry passed=false.
        if isinstance(data, dict) and ('final' in data or 'readback' in data):
            ok = ok and data.get('final', {}).get('passed', True) is not False
            ok = ok and data.get('readback', {}).get('passed', True) is not False
        if isinstance(data, dict) and set(data) == {'text'}:
            data = decode_text(data['text'])
    if isinstance(data, str) and re.match(r'^\s*(error\b|failed\b|exception\b)', data, re.I):
        ok = False
    return {'ok': ok, 'data': data, 'uncertain': uncertain,
            **({} if ok else {'error': 'UPSTREAM_UNCERTAIN' if uncertain else 'UPSTREAM_FAILED'})}


class Backends:
    def __init__(self, config, folder):
        self.config, self.folder = config, Path(folder)
        self.sessions, self.schemas = {}, {}

    async def __aenter__(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        try:
            self.log = self.stack.enter_context(open(self.folder / 'upstream.stderr.log', 'a', encoding='utf-8'))
            for name in SERVERS:
                conf = self.config[name]
                params = StdioServerParameters(command=conf['command'], args=conf['args'], env=conf['env'])
                streams = await self.stack.enter_async_context(stdio_client(params, errlog=self.log))
                session = await self.stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=timedelta(seconds=7200)))
                await session.initialize()
                self.sessions[name] = session
                definitions = await session.list_tools()
                self.schemas[name] = {t.name: t.model_dump(mode='json', exclude_none=True) for t in definitions.tools}
            return self
        except BaseException:
            await self.stack.__aexit__(*__import__('sys').exc_info())
            raise

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)

    async def call(self, server, tool, arguments):
        result = await self.sessions[server].call_tool(tool, arguments)
        return result.model_dump(mode='json', exclude_none=True)


class Engine:
    def __init__(self, workspace, config, node, worker=None, backend_factory=Backends):
        self.root = Path(workspace).resolve() / 'code-mode'
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'runs.sqlite'
        self.config, self.node = config, str(node)
        self.worker = Path(worker or Path(__file__).parent / 'runtime/worker.mjs').resolve()
        self.backend_factory = backend_factory
        self.tasks = set()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,digest TEXT NOT NULL,record TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, record):
        with self.connect() as db:
            db.execute('UPDATE runs SET record=? WHERE id=?', (encode(record), record['request_id']))

    def status(self, request_id):
        with self.connect() as db:
            row = db.execute('SELECT record FROM runs WHERE id=?', (request_id,)).fetchone()
        if not row:
            return {'request_id': request_id, 'status': 'NOT_FOUND', 'no_replay': True}
        record = json.loads(row[0])
        # Never return raw tool contents or code from polling.
        return {k: v for k, v in record.items() if k != 'code'}

    async def start(self, request_id, code):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id or ''):
            raise ValueError('Invalid request_id')
        if not isinstance(code, str) or not 0 < len(code.encode('utf-8')) <= 65536:
            raise ValueError('Program must be 1–65536 UTF-8 bytes')
        digest = hashlib.sha256(code.encode()).hexdigest()
        record = {'request_id': request_id, 'code_sha256': digest, 'status': 'RUNNING',
            'calls': 0, 'raw_tool_bytes': 0, 'guest_result_bytes': 0,
            'completion': 'NOT_YET_KNOWN', 'no_replay': True, 'code': code,
            'evidence_directory': str(self.root / request_id), 'runner_pid': os.getpid(),
            'geometry_verified': False, 'started_at': time.time()}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT digest FROM runs WHERE id=?', (request_id,)).fetchone()
            if prior:
                if prior[0] != digest:
                    raise ValueError('request_id consumed with different program')
                return {**self.status(request_id), 'cached_no_dispatch': True}
            records = [json.loads(r[0]) for r in db.execute('SELECT record FROM runs')]
            if any(r['status'] in ('RUNNING', 'UNCERTAIN') for r in records):
                return {'status': 'REJECTED_BUSY', 'completion': 'NOT_DISPATCHED', 'no_replay': True}
            db.execute('INSERT INTO runs VALUES(?,?,?)', (request_id, digest, encode(record)))
        folder = self.root / request_id
        folder.mkdir(exist_ok=False)
        (folder / 'program.js').write_text(code, encoding='utf-8')
        task = asyncio.create_task(self.run(record))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.status(request_id)

    async def catalog(self, server, names):
        if server not in SERVERS:
            raise ValueError('Unknown server')
        if not isinstance(names, list) or len(names) > 12:
            raise ValueError('Select up to 12 tool schemas')
        async with self.backend_factory(self.config, self.root) as backends:
            entries = backends.schemas[server]
            if names:
                return {'server': server, 'tools': [entries[n] for n in names]}
            return {'server': server, 'tools': [{'name': t['name'], 'description': t.get('description', '')[:220]} for t in entries.values()]}

    async def run(self, record):
        folder = Path(record['evidence_directory'])
        process = None
        in_flight = False
        stopped = False
        try:
            async with self.backend_factory(self.config, folder) as backends:
                # No secrets, files, sockets or processes are injected into guest.
                # Node is trusted runtime; its environment is also minimized.
                child_env = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')}
                with open(folder / 'sandbox.stderr.log', 'wb') as errors:
                    process = await asyncio.create_subprocess_exec(self.node, str(self.worker),
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=errors, env=child_env, limit=9 * 1024 * 1024,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    tables = {alias: {'server': name, 'names': list(backends.schemas[name])} for alias, name in ALIASES.items()}
                    process.stdin.write((encode({'code': record['code'], 'tools': tables}) + '\n').encode())
                    await process.stdin.drain()
                    program_started = time.monotonic()
                    seen_call_ids = set()
                    while True:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=10)
                        if not line:
                            raise RuntimeError('Sandbox closed without a final result')
                        event = json.loads(line)
                        if event.get('type') != 'call':
                            if event.get('type') == 'done' and not stopped:
                                output = event.get('value')
                                assert len(encode(output).encode()) <= 8192
                                record.update(status='SUCCEEDED', completion='KNOWN_FINISHED', output=output,
                                    guest_cpu_ms=event.get('guest_cpu_ms'), guest_result_bytes=len(encode(output).encode()))
                            else:
                                record.update(status='UNCERTAIN' if record.get('upstream_uncertain') else 'FAILED',
                                    completion='UNCERTAIN' if record.get('upstream_uncertain') else 'KNOWN_FINISHED',
                                    error=record.get('error', event.get('error', 'PROGRAM_STOPPED')))
                            break
                        # Requests from Promise.all are serviced sequentially.
                        sequence = record['calls'] + 1
                        reply = {'ok': False, 'error': 'PROGRAM_STOPPED'}
                        server, tool, args = event.get('server'), event.get('tool'), event.get('arguments')
                        if type(event.get('id')) is not int or event['id'] in seen_call_ids:
                            raise RuntimeError('Duplicate/unbound guest bridge ID')
                        seen_call_ids.add(event['id'])
                        if not stopped:
                            if sequence > 100 or time.monotonic() - program_started > 7200:
                                stopped = True
                                record['error'] = 'PROGRAM_CALL_OR_WALL_LIMIT'
                            else:
                                # Validate against real loaded tool schemas before dispatch.
                                schema = backends.schemas.get(server, {}).get(tool)
                                if schema is None or not isinstance(args, dict) or len(encode(args).encode()) > 262144:
                                    stopped = True
                                    record['error'] = 'INVALID_TOOL_OR_ARGUMENTS'
                                else:
                                    try:
                                        validate(args, schema['inputSchema'])
                                    except Exception:
                                        stopped = True
                                        record['error'] = 'ARGUMENT_SCHEMA_REJECTED'
                        if not stopped:
                            record['calls'] = sequence
                            record['last_call'] = {'sequence': sequence, 'server': server, 'tool': tool, 'phase': 'DISPATCH_INTENT'}
                            intent = {'server': server, 'tool': tool, 'arguments': args, 'call_id': event['id']}
                            (folder / f'{sequence:03d}-intent.json').write_text(encode(intent), encoding='utf-8')
                            self.save(record)  # durable before actual MCP call
                            in_flight = True
                            raw = await backends.call(server, tool, args)
                            # Persist full result before handing it back to the guest.
                            raw_bytes = encode(raw).encode('utf-8')
                            (folder / f'{sequence:03d}-result.json').write_bytes(raw_bytes)
                            record['raw_tool_bytes'] += len(raw_bytes)
                            reply = project(raw)
                            in_flight = False
                            # Strip inline image bytes; retain images in raw evidence.
                            reply['images'] = sum(c.get('type') == 'image' for c in raw.get('content', []))
                            if len(encode(reply).encode()) > 8 * 1024 * 1024:
                                reply = {'ok': False, 'error': 'TOOL_RESULT_EXCEEDS_GUEST_LIMIT'}
                            record['last_call']['phase'] = 'RETURNED'
                            if not reply['ok']:
                                stopped = True
                                record['error'] = reply['error']
                                record['upstream_uncertain'] = reply.get('uncertain', False)
                            self.save(record)
                        else:
                            reply['error'] = record.get('error', 'PROGRAM_STOPPED')
                        process.stdin.write((encode({'id': event['id'], 'result': reply}) + '\n').encode())
                        await process.stdin.drain()
                    process.stdin.close()
                    await asyncio.wait_for(process.wait(), 10)
        except BaseException as error:
            # Process/client timeout is never proof that an upstream CAD call ended.
            uncertain = in_flight or record.get('upstream_uncertain', False)
            record.update(status='UNCERTAIN' if uncertain else 'FAILED', completion='UNCERTAIN' if uncertain else 'KNOWN_FINISHED',
                error=f'{type(error).__name__}: {str(error)[:800]}')
        finally:
            if process is not None and process.returncode is None:
                # Only our QuickJS subprocess; never kill CATIA or an MCP backend.
                process.kill()
                await process.wait()
            record['finished_at'] = time.time()
            self.save(record)


def load_config(path):
    root = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if set(root) != set(SERVERS):
        raise ValueError('Expected exactly two existing CATIA backends')
    for conf in root.values():
        if set(conf['env']) - {'PHYXI_NATIVE_WORKSPACE', 'PHYXI_NATIVE_GATE', 'CATIA_MCP_LOG_FILE'}:
            raise ValueError('Unexpected backend environment keys')
    envs = [root[n]['env'] for n in SERVERS]
    for key in ('PHYXI_NATIVE_WORKSPACE', 'PHYXI_NATIVE_GATE'):
        if not envs[0].get(key) or envs[0][key] != envs[1][key]:
            raise ValueError('Backends must share execution context: ' + key)
    return root
