"""Durable sequential CATIA tool plans; no replay, rollback or invented geometry checks."""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from native_gate import SessionGate, GateBlocked, GateBusy, utc


class PlanInputError(ValueError):
    """Rejected before dispatch; never used for a runtime failure."""


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def pointer(value, path):
    if path == '': return value
    if not path.startswith('/'): raise ValueError('Expected a JSON pointer beginning with /')
    for key in path[1:].split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def normalize(tool, raw, duration=0):
    """Transport success and measured geometry success are separate facts."""
    if hasattr(raw, 'model_dump'): raw = raw.model_dump(mode='json', exclude_none=True)
    if isinstance(raw, str): raw = {'content': [{'type': 'text', 'text': raw}]}
    if not isinstance(raw, dict): raise TypeError('Tool result must be a dict, string or MCP result')
    data = raw.get('structuredContent')
    text = '\n'.join(p.get('text', '') for p in raw.get('content', []) if p.get('type') == 'text')
    if not isinstance(data, dict):
        try: data = json.loads(text)
        except (ValueError, TypeError): data = None
    if 'ok' in raw and 'content' not in raw: data = raw
    ok = not raw.get('isError', False)
    if isinstance(data, dict) and 'ok' in data: ok = ok and data['ok'] is True
    if re.match(r'^\s*(error\b|failed\b|exception\b)', text, re.I): ok = False
    effects = data.get('effects', {'modified': None}) if isinstance(data, dict) else {'modified': None}
    code = data.get('code', 'RETURNED' if ok else 'TOOL_FAILED') if isinstance(data, dict) else ('RETURNED' if ok else 'LEGACY_ERROR')
    uncertain = code in ('COM_ERROR', 'RPC_ERROR', 'TIMEOUT', 'UNKNOWN_EXECUTION') and effects.get('modified') is not False
    diagnostic = text + '\n' + (str(data.get('message', '')) if isinstance(data, dict) else '')
    # A bound synchronous Automation E_FAIL/invalid-argument/type error is a
    # finished failure. Unknown partial geometry is distinct from a live RPC.
    returned_hresult = re.search(r'(?<!\d)(-2147467259|-2147024809|-2147352573|-2147352571)(?!\d)', diagnostic)
    if code == 'COM_ERROR' and returned_hresult: uncertain = False
    if re.search(r'RPC_E_|RPC_S_|0x80010[018]|0x800706b[aef]|-2147417848|-2147023174', diagnostic, re.I): uncertain = True
    no_active_document = (tool == 'catia_get_active_document_info' and not ok and code == 'COM_ERROR'
        and isinstance(data, dict) and data.get('tool') == tool
        and data.get('message') == 'No active document in CATIA. Create or open a document first.'
        and data.get('data') == {'failure_stage': 'execute'})
    if no_active_document:
        uncertain = False
        effects = {'modified': False}
    return {'tool': tool, 'ok': ok, 'code': code, 'completion': 'UNCERTAIN' if uncertain else 'KNOWN_FINISHED',
            'duration_ms': round(duration * 1000, 2), 'effects': effects,
            'verification': {'status': 'NOT_REQUESTED', 'checks': []},
            'completion_evidence': ({'precondition': 'NO_ACTIVE_DOCUMENT_READ_ONLY'} if no_active_document else
                {'returned_hresult': returned_hresult.group(1)} if returned_hresult and not uncertain else {}),
            'data': data if data is not None else {'text': text}, 'raw': raw}


def verify(feedback, assertions):
    checks = []
    for assertion in assertions:
        entry = dict(assertion)
        try:
            actual = pointer(feedback['data'], assertion['path'])
            expected = assertion['value']; op = assertion.get('op', 'eq')
            numeric = type(actual) in (int, float) and type(expected) in (int, float)
            if numeric and not (math.isfinite(actual) and math.isfinite(expected)): raise ValueError('nonfinite measurement')
            if op == 'eq': passed = abs(actual - expected) <= assertion.get('tolerance', 0) if numeric else type(actual) is type(expected) and actual == expected
            else:
                if not numeric: raise ValueError('Numeric comparison requires actual and expected numbers')
                passed = {'gt': actual > expected, 'ge': actual >= expected,
                          'lt': actual < expected, 'le': actual <= expected}[op]
            entry.update(actual=actual, passed=passed)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            entry.update(passed=False, error=type(error).__name__)
        checks.append(entry)
    if checks:
        feedback['verification'] = {'status': 'PASSED' if all(c['passed'] for c in checks) else 'FAILED', 'checks': checks}
        if feedback['verification']['status'] == 'FAILED':
            feedback.update(ok=False, code='RESULT_CHECK_FAILED')
    return feedback


class PlanEngine:
    def __init__(self, workspace, gate, dispatch, validate=lambda name, args: None):
        self.folder = Path(workspace) / 'tool-plans'; self.folder.mkdir(parents=True, exist_ok=True)
        self.db = self.folder / 'plans.sqlite'
        self.gate = SessionGate(gate)
        self.dispatch, self.validate = dispatch, validate
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, digest TEXT NOT NULL, record TEXT NOT NULL)')
        self.reconcile_returned_failures()

    def reconcile_returned_failures(self):
        """Only bound terminal error evidence can repair an older classification."""
        with self.connect() as db:
            rows = db.execute('SELECT record FROM plans').fetchall()
        for row in rows:
            record = json.loads(row[0])
            if record['status'] != 'UNCERTAIN' or not record['results']: continue
            last = record['results'][-1]
            corrected = normalize(last['tool'], last['raw'])
            if corrected['ok'] or corrected['completion'] != 'KNOWN_FINISHED' or not corrected['completion_evidence']: continue
            digest = hashlib.sha256(encoded(record).encode()).hexdigest()
            with self.gate._transaction() as db:
                gate = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
                if gate['status'] != 'FROZEN' or gate['operation'] != 'catia-plan:' + record['request_id']: continue
                self.gate._event(db, 'plan_known_returned_failure_reconciled', gate['owner'],
                    {'request_id': record['request_id'], 'previous_record_sha256': digest,
                     'raw_result_sha256': hashlib.sha256(encoded(last['raw']).encode()).hexdigest(), **corrected['completion_evidence'], 'no_replay': True})
                db.execute("UPDATE gate SET status='IDLE',owner=NULL,operation=NULL,pid=NULL,updated_at=? WHERE singleton=1", (utc(),))
            # Preserve original result classification and raw bytes, add an audit.
            record.update(status='FAILED', completion='KNOWN_FINISHED',
                          reconciliation={'previous_record_sha256': digest, 'at': utc(), 'no_replay': True, **corrected['completion_evidence']})
            self.save(record)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def status(self, request_id=None):
        with self.connect() as db:
            if request_id:
                row = db.execute('SELECT record FROM plans WHERE id=?', (request_id,)).fetchone()
                return json.loads(row[0]) if row else {'status': 'NOT_FOUND', 'request_id': request_id}
            rows = db.execute('SELECT record FROM plans ORDER BY rowid DESC LIMIT 30').fetchall()
        return {'gate': self.gate.snapshot(), 'plans': [json.loads(r[0]) for r in rows]}

    def save(self, record):
        record['updated_at'] = utc()
        with self.connect() as db:
            db.execute('UPDATE plans SET record=? WHERE id=?', (encoded(record), record['request_id']))

    def preflight(self, request_id, steps):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id): raise ValueError('Invalid request_id')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30: raise ValueError('A plan requires 1–30 ordered steps')
        ids = set()
        for step in steps:
            if not isinstance(step, dict) or set(step) - {'id', 'tool', 'arguments', 'expect'}: raise ValueError('Invalid step fields')
            if not isinstance(step.get('id'), str) or step['id'] in ids: raise ValueError('Each step needs a unique id')
            ids.add(step['id'])
            if not isinstance(step.get('tool'), str) or step['tool'].startswith('catia_plan_'): raise ValueError('Nested plans are not supported')
            if not isinstance(step.get('arguments', {}), dict): raise ValueError('arguments must be an object')
            self.validate(step['tool'], step.get('arguments', {}))
            if not isinstance(step.get('expect', []), list): raise ValueError('expect must be a list')
            for check in step.get('expect', []):
                if set(check) - {'path', 'op', 'value', 'tolerance'} or not isinstance(check.get('path'), str) or 'value' not in check: raise ValueError('Invalid expected result')
                if check['path'] and not check['path'].startswith('/'): raise ValueError('Use JSON pointer paths')
                if check.get('op', 'eq') not in ('eq', 'gt', 'ge', 'lt', 'le'): raise ValueError('Invalid comparison')
                if type(check.get('tolerance', 0)) not in (float, int) or check.get('tolerance', 0) < 0: raise ValueError('Invalid tolerance')
        encoded(steps)

    def run(self, request_id, steps):
        # All input schemas are checked before the first CAD dispatch.
        try: self.preflight(request_id, steps)
        except Exception as error: raise PlanInputError(str(error)) from error
        digest = hashlib.sha256(encoded(steps).encode()).hexdigest()
        record = {'request_id': request_id, 'digest': digest, 'status': 'CLAIMED', 'completion': 'UNCERTAIN',
                  'created_at': utc(), 'steps': steps, 'results': [], 'events': [], 'automatic_retry_allowed': False,
                  'rollback_supported': False, 'geometry_verified': False}
        with self.connect() as db:
            try: db.execute('INSERT INTO plans VALUES(?,?,?)', (request_id, digest, encoded(record)))
            except sqlite3.IntegrityError:
                row = db.execute('SELECT digest,record FROM plans WHERE id=?', (request_id,)).fetchone()
                if row[0] != digest: raise PlanInputError('request_id consumed with different input')
                cached = json.loads(row[1]); cached['cached_no_CAD_dispatch'] = True
                return cached
        try: owner = self.gate.acquire('catia-plan:' + request_id)
        except (GateBlocked, GateBusy) as error:
            record.update(status='REJECTED_BUSY', completion='NOT_DISPATCHED', message=str(error)); self.save(record); return record
        record['status'] = 'RUNNING'; self.save(record)
        try:
            for step in steps:
                record['events'].append({'type': 'step_started', 'step': step['id'], 'tool': step['tool'], 'at': utc()})
                self.save(record)
                started = time.monotonic()
                raw = self.dispatch(step['tool'], step.get('arguments', {}))
                result = verify(normalize(step['tool'], raw, time.monotonic() - started), step.get('expect', []))
                result['step'] = step['id']; record['results'].append(result)
                record['events'].append({'type': 'step_finished', 'step': step['id'], 'ok': result['ok'], 'code': result['code'], 'at': utc()})
                self.save(record)
                if not result['ok'] or result['completion'] == 'UNCERTAIN':
                    record.update(status='UNCERTAIN' if result['completion'] == 'UNCERTAIN' else 'FAILED', completion=result['completion'])
                    break
            else: record.update(status='SUCCEEDED', completion='KNOWN_FINISHED')
            # PASSED means declared assertions passed, not general CAD acceptance.
            checks = [r['verification'] for r in record['results'] if r['verification']['checks']]
            record['declared_checks_passed'] = bool(checks) and all(c['status'] == 'PASSED' for c in checks)
            record['skipped_steps'] = [s['id'] for s in steps[len(record['results']):]]
            if record['completion'] == 'UNCERTAIN':
                self.gate.freeze(owner, 'Plan step returned uncertain CAD execution; do not replay')
            else:
                self.gate.complete(owner, {'request_id': request_id, 'status': record['status'], 'step_results': len(record['results']), 'execution_finished': True})
            self.save(record)
            return record
        except BaseException as error:
            # Error after dispatch cannot imply completion or rollback.
            record.update(status='UNCERTAIN', completion='UNCERTAIN', error_type=type(error).__name__)
            self.save(record)
            if self.gate.snapshot()['status'] == 'RUNNING': self.gate.freeze(owner, 'Plan worker exited without final completion evidence')
            raise


PLAN_TOOLS = [
    {'name': 'catia_plan_run', 'description': 'Execute 1–30 ordered CATIA tools with one request_id. Validates all inputs first, holds one shared CATIA mutex for the whole plan, stops on first failure. Optional expect checks use JSON pointers into returned structured data. No replay, no rollback; check results and declared assertions. SUCCEEDED alone is not geometry acceptance.',
     'inputSchema': {'type': 'object', 'properties': {'request_id': {'type': 'string'}, 'steps': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'tool': {'type': 'string'}, 'arguments': {'type': 'object'}, 'expect': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['id', 'tool'], 'additionalProperties': False}}}, 'required': ['request_id', 'steps'], 'additionalProperties': False}},
    {'name': 'catia_plan_status', 'description': 'Read durable plan progress/results without COM dispatch. No request_id returns compact recent plan summaries; request_id returns complete recorded evidence. Available while a plan is running. Observation only, never replay or unlock.', 'inputSchema': {'type': 'object', 'properties': {'request_id': {'type': 'string'}}, 'additionalProperties': False}},
    {'name': 'catia_plan_catalog', 'description': 'List CATIA tools without COM. Default returns concise names/descriptions. To inspect exact input schemas, pass specific names and include_schema=true; avoid returning all schemas in one model context.', 'inputSchema': {'type': 'object', 'properties': {'names': {'type': 'array', 'maxItems': 101, 'items': {'type': 'string'}}, 'include_schema': {'type': 'boolean'}}, 'additionalProperties': False}}
]
