"""Automatic, durable one-use CATIA execution; no interactive approval."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from native_contract import sha, screen_macro, validate_checks, validate_program_checks
from native_gate import SessionGate, GateBlocked, utc

ROOT = Path(__file__).resolve().parent


class NativeService(SessionGate):
    def __init__(self, workspace, gate=None):
        self.workspace = Path(workspace).resolve()
        self.jobs = self.workspace / 'native-modeling' / 'jobs'
        self.jobs.mkdir(parents=True, exist_ok=True)
        super().__init__(gate or self.workspace / 'native-modeling' / 'execution.sqlite')
        with self._transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS native_ui_jobs(
              job_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('APPROVED','RUNNING','SUCCEEDED','FAILED','FROZEN')),
              owner TEXT,result_json TEXT,updated_at TEXT NOT NULL)''')
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='native_ui_jobs'").fetchone()[0]
            if "'FAILED'" not in schema:
                db.execute('ALTER TABLE native_ui_jobs RENAME TO native_ui_jobs_before_063')
                db.execute('''CREATE TABLE native_ui_jobs(
                  job_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL,
                  state TEXT NOT NULL CHECK(state IN ('APPROVED','RUNNING','SUCCEEDED','FAILED','FROZEN')),
                  owner TEXT,result_json TEXT,updated_at TEXT NOT NULL)''')
                db.execute('INSERT INTO native_ui_jobs SELECT * FROM native_ui_jobs_before_063')
                db.execute('DROP TABLE native_ui_jobs_before_063')
                self._event(db, 'native_schema_063', None, {'added_terminal_state': 'FAILED'})
        self.reconcile_terminal_failure()

    def folder(self, job):
        if not isinstance(job, str) or not re.fullmatch(r'native-[0-9a-f]{24}', job):
            raise ValueError('Invalid native job id')
        p = self.jobs / job
        if not p.is_dir() or p.is_symlink() or p.is_junction() or p.resolve().parent != self.jobs.resolve():
            raise ValueError('Unbound job directory')
        return p

    def prepare(self, requirement, proposal, expected_hash=None, *, job_id=None):
        """Automatically bind a request to executable bytes and readback checks."""
        if self.snapshot()['status'] != 'IDLE':
            raise GateBlocked('CATIA仍在运行或缺少结束证据；明确结束的几何失败会自动释放入口，无需人工审核。')
        raw, checks = validate_program_checks(proposal['macro_ascii'], proposal['checks'])
        # Integrity binding is automatic, independent of human approval.
        actual_hash = sha(json.dumps(proposal, sort_keys=True, ensure_ascii=False).encode())
        if expected_hash is None:
            expected_hash = actual_hash
        if sha(json.dumps(proposal, sort_keys=True, ensure_ascii=False).encode()) != expected_hash:
            raise ValueError('方案数据发生变化，请重新生成')
        job = job_id or 'native-' + uuid.uuid4().hex[:24]
        if not isinstance(job, str) or not re.fullmatch(r'native-[0-9a-f]{24}', job):
            raise ValueError('Invalid native job id')
        folder = self.jobs / job
        folder.mkdir(exist_ok=False)
        (folder / 'REVIEWED.CATScript').write_bytes(raw)
        (folder / 'CHECKS.json').write_text(json.dumps(checks, ensure_ascii=True, allow_nan=False), encoding='utf-8')
        check_hash = sha((folder / 'CHECKS.json').read_bytes())
        source = (ROOT / 'bridge' / 'NativeModeling.cs').read_text(encoding='utf-8')
        for token, value in [('__ROOT__', str(folder).replace('"', '""')), ('__MACRO_SHA__', sha(raw)),
                             ('__CHECK_SHA__', check_hash), ('__RUN_ID__', job)]:
            source = source.replace(token, value)
        (folder / 'NativeModeling.cs').write_text(source, encoding='utf-8')
        exe = folder / 'NativeModeling.exe'
        compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        completed = subprocess.run([str(compiler), '/nologo', '/target:exe', '/platform:x64',
                                    '/r:Microsoft.CSharp.dll', '/r:System.Web.Extensions.dll',
                                    '/out:' + str(exe), str(folder / 'NativeModeling.cs')],
                                   capture_output=True, timeout=40, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (folder / 'compile.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('原生桥编译失败，未调用CATIA；请查看compile.log')
        manifest = {'job_id': job, 'requirement': requirement, 'summary': proposal.get('summary', ''),
                    'approval_origin': 'user_authorized_automatic_execution', 'prepared_at': utc(),
                    'interactive_approval_required': False,
                    'macro_sha256': sha(raw), 'checks_sha256': check_hash, 'bridge_sha256': sha(exe.read_bytes()),
                    'proposal_sha256': expected_hash,
                    'checks_origin': 'model_proposed_automatically_bound_not_independent_requirement_oracle'}
        (folder / 'approval.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.register(manifest)
        return manifest

    def verify(self, manifest):
        folder = self.folder(manifest['job_id'])
        for name, key in [('REVIEWED.CATScript', 'macro_sha256'), ('CHECKS.json', 'checks_sha256'), ('NativeModeling.exe', 'bridge_sha256')]:
            p = folder / name
            if p.is_symlink() or not p.is_file() or sha(p.read_bytes()) != manifest[key]:
                raise ValueError('批准文件哈希变化；拒绝派发')
        raw, _ = validate_program_checks((folder / 'REVIEWED.CATScript').read_bytes().decode('ascii'),
                                        json.loads((folder / 'CHECKS.json').read_text(encoding='utf-8')))
        return folder, raw

    def register(self, manifest):
        # Accept historical records as well as the new automatic execution mode.
        if manifest.get('approval_origin') not in ('local_ui_full_source_review', 'user_authorized_automatic_execution'):
            raise ValueError('Unknown execution provenance')
        self.verify(manifest)
        with self._transaction() as db:
            db.execute("INSERT INTO native_ui_jobs VALUES (?,?,'APPROVED',NULL,NULL,?)",
                       (manifest['job_id'], json.dumps(manifest, sort_keys=True), utc()))
            self._event(db, 'native_ui_approved', None, {'job_id': manifest['job_id'], 'macro_sha256': manifest['macro_sha256']})

    def job(self, job):
        self.folder(job)
        with self._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            if row is None:
                raise ValueError('没有任务记录')
            return dict(row)

    def claim(self, job, code):
        raw = code.encode('ascii', errors='strict')
        with self._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            if row is None:
                raise ValueError('Unknown job; use modeling_execute to create and execute automatically')
            manifest = json.loads(row['manifest_json'])
            if sha(raw) != manifest['macro_sha256']:
                raise ValueError('Source differs from approval; no CAD dispatch')
            if row['state'] in ('SUCCEEDED', 'FAILED'):
                return {'cached': json.loads(row['result_json'])}
            screen_macro(code)
            if row['state'] != 'APPROVED':
                raise GateBlocked('任务已消费或结果未知；禁止重放')
            folder, stored = self.verify(manifest)
            gate = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if gate['status'] != 'RUNNING' or gate['operation'] != 'native_pending:' + job or gate['owner'] != row['owner']:
                raise GateBlocked('任务尚未取得执行互斥锁，或上次结果未知；禁止并发派发')
            if stored != raw or any((folder / x).exists() for x in ['RESULT.CATPart', 'RESULT.jpg', 'execute.stdout.jsonl', 'execute.stderr.log']):
                raise ValueError('已存在执行痕迹；禁止重放')
            owner = gate['owner']
            db.execute("UPDATE native_ui_jobs SET state='RUNNING',owner=?,updated_at=? WHERE job_id=?", (owner, utc(), job))
            db.execute("UPDATE gate SET status='RUNNING',owner=?,operation=?,pid=NULL,updated_at=? WHERE singleton=1", (owner, 'native_ui:' + job, utc()))
            self._event(db, 'native_ui_dispatch_intent', owner, {'job_id': job, 'macro_sha256': manifest['macro_sha256']})
        return {'owner': owner, 'manifest': manifest, 'folder': folder}

    def reserve(self, job):
        """Automatic mutual exclusion before sending the model execution prompt."""
        with self._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            gate = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row is None or row['state'] != 'APPROVED' or row['owner'] is not None or gate['status'] != 'IDLE':
                raise GateBlocked('本任务已保留/消费或执行门非IDLE；不重复提交')
            self.verify(json.loads(row['manifest_json']))
            owner = uuid.uuid4().hex
            db.execute('UPDATE native_ui_jobs SET owner=?,updated_at=? WHERE job_id=?', (owner, utc(), job))
            db.execute("UPDATE gate SET status='RUNNING',owner=?,operation=?,pid=NULL,updated_at=? WHERE singleton=1", (owner, 'native_pending:' + job, utc()))
            self._event(db, 'native_ui_model_prompt_reserved', owner, {'job_id': job, 'no_CAD_dispatch_yet': True})

    def settle_without_dispatch(self, job, evidence):
        """Terminal model turn observed locally with zero modeling calls, job unclaimed.

        Consumes this task without replay. Not a timeout/unknown-state unlock.
        """
        with self._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            gate = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row is None or row['state'] != 'APPROVED' or gate['operation'] != 'native_pending:' + job or gate['owner'] != row['owner']:
                raise GateBlocked('Cannot settle a claimed or unrelated operation')
            db.execute("UPDATE native_ui_jobs SET state='FROZEN',updated_at=? WHERE job_id=?", (utc(), job))
            self._event(db, 'native_ui_terminal_no_dispatch', row['owner'], {'job_id': job, 'evidence': evidence, 'task_consumed_no_retry': True})
            db.execute("UPDATE gate SET status='IDLE',owner=NULL,operation=NULL,pid=NULL,updated_at=? WHERE singleton=1", (utc(),))

    def finish(self, job, owner, result=None, *, failed=False):
        with self._transaction() as db:
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            gate = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row is None or row['owner'] != owner or row['state'] != 'RUNNING' or gate['owner'] != owner or gate['status'] != 'RUNNING':
                raise GateBlocked('Owner/state mismatch; no recovery')
            state = ('FAILED' if failed else 'SUCCEEDED') if result is not None else 'FROZEN'
            db.execute('UPDATE native_ui_jobs SET state=?,result_json=?,updated_at=? WHERE job_id=?',
                       (state, None if result is None else json.dumps(result), utc(), job))
            if result is None:
                db.execute("UPDATE gate SET status='FROZEN',updated_at=? WHERE singleton=1", (utc(),))
            else:
                db.execute("UPDATE gate SET status='IDLE',owner=NULL,operation=NULL,pid=NULL,updated_at=? WHERE singleton=1", (utc(),))
            self._event(db, 'native_ui_' + state.lower(), owner, {'job_id': job})

    def terminal_failure_result(self, job, manifest, rows, exit_record):
        """Classify only bound terminal returns, including explicit script errors."""
        terminal = [r.get('detail', {}) for r in rows if r.get('name') == 'execution_finished']
        if (not exit_record.get('child_return_observed') or exit_record.get('returncode') not in (2, 3) or
                len(terminal) != 1 or not rows or rows[-1].get('name') != 'execution_finished'):
            return None
        end = terminal[0]
        if (end.get('run_id') != job or end.get('macro_sha256') != manifest['macro_sha256'] or
                end.get('checks_sha256') != manifest['checks_sha256'] or
                end.get('com_return_observed') is not True or end.get('outcome') != 'FAILED' or
                len([r for r in rows if r.get('name') == 'com_return_observed']) != 1):
            return None
        failure = next((r['detail'] for r in rows if r.get('name') == 'validation_failed'), None)
        script_errors = [r['detail'] for r in rows if r.get('name') == 'macro_runtime_failed']
        script_error = script_errors[0] if len(script_errors) == 1 else None
        if end.get('script_error_returned') or script_errors:
            if (script_error is None or script_error.get('known_script_engine_return') is not True or
                    end.get('script_error_returned') is not True or
                    script_error.get('run_id') != job or script_error.get('macro_sha256') != manifest['macro_sha256'] or
                    script_error.get('checks_sha256') != manifest['checks_sha256']):
                return None
        readback = next((r['detail'] for r in rows if r.get('name') == 'independent_readback'), None)
        result = {'job_id': job, 'state': 'FAILED', 'passed': False, 'completion': 'KNOWN_FINISHED',
                  'interactive_approval_required': False, 'gate_released_automatically': True,
                  'readback': readback, 'diagnostic': failure, 'script_error': script_error, 'exit_code': exit_record['returncode'],
                  'reason': 'macro_runtime_error' if script_error else ('geometry_validation_failed' if failure else 'post_COM_operation_failed'),
                  'next_action': 'Correct the macro and submit a NEW request_id automatically; never repeat this consumed request.',
                  'cached_no_CAD_dispatch': False, 'same_request_replay_allowed': False}
        return result

    def terminal_failure(self, job, owner, manifest, rows, exit_record):
        result = self.terminal_failure_result(job, manifest, rows, exit_record)
        if result is None:
            return None
        folder = self.folder(job)
        (folder / 'terminal-failure.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.finish(job, owner, result, failed=True)
        return result

    def reconcile_terminal_failure(self):
        """Recover a persisted terminal failure after a service interruption, no CAD."""
        with self._transaction() as db:
            gate = dict(db.execute('SELECT * FROM gate WHERE singleton=1').fetchone())
            if gate['status'] != 'FROZEN' or not str(gate['operation']).startswith('native_ui:'):
                return False
            job = gate['operation'].split(':', 1)[1]
            row = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
            if row is None or row['state'] != 'FROZEN' or row['owner'] != gate['owner']:
                return False
            manifest = json.loads(row['manifest_json'])
            folder, _ = self.verify(manifest)
            exit_path = folder / 'bridge-exit.json'
            if not exit_path.exists():
                return False
            evidence = json.loads(exit_path.read_text(encoding='utf-8'))
            if (not evidence.get('child_return_observed') or evidence.get('returncode') not in (2, 3) or
                    evidence.get('bridge_sha256') != manifest['bridge_sha256'] or
                    evidence.get('stdout_sha256') != sha((folder / 'execute.stdout.jsonl').read_bytes())):
                return False
            rows = [json.loads(x) for x in (folder / 'execute.stdout.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
            result = self.terminal_failure_result(job, manifest, rows, evidence)
            if result is None:
                return False
            db.execute("UPDATE native_ui_jobs SET state='FAILED',result_json=?,updated_at=? WHERE job_id=?", (json.dumps(result), utc(), job))
            self._event(db, 'native_terminal_failure_auto_reconciled', gate['owner'], {'job_id': job, 'exit_sha256': sha(exit_path.read_bytes())})
            db.execute("UPDATE gate SET status='IDLE',owner=NULL,operation=NULL,pid=NULL,updated_at=? WHERE singleton=1", (utc(),))
        return True

    def run(self, job_id, macro_ascii):
        claimed = self.claim(job_id, macro_ascii)
        if 'cached' in claimed:
            return {**claimed['cached'], 'cached_no_CAD_dispatch': True}
        folder, manifest, owner = claimed['folder'], claimed['manifest'], claimed['owner']
        try:
            self.verify(manifest)
            with (folder / 'execute.stdout.jsonl').open('xb') as out, (folder / 'execute.stderr.log').open('xb') as err:
                completed = subprocess.run([str(folder / 'NativeModeling.exe')], stdout=out, stderr=err, timeout=120,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            exit_record = {'child_return_observed': True, 'returncode': completed.returncode, 'at': utc(),
                           'bridge_sha256': manifest['bridge_sha256'],
                           'stdout_sha256': sha((folder / 'execute.stdout.jsonl').read_bytes())}
            (folder / 'bridge-exit.json').write_text(json.dumps(exit_record, indent=2), encoding='utf-8')
            rows = [json.loads(x) for x in (folder / 'execute.stdout.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
            (folder / 'execute.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            if completed.returncode:
                terminal = self.terminal_failure(job_id, owner, manifest, rows, exit_record)
                if terminal is not None:
                    return terminal
                raise RuntimeError('Trusted bridge failed')
            observed = {}
            for event in ['dispatch_attempted', 'com_return_observed', 'independent_readback', 'reopened_readback', 'experiment_validated']:
                matches = [r['detail'] for r in rows if r['name'] == event]
                if len(matches) != 1:
                    raise RuntimeError('Required event cardinality failed')
                observed[event] = matches[0]
            for event in ['independent_readback', 'reopened_readback', 'experiment_validated']:
                if observed[event].get('passed') is not True:
                    raise RuntimeError('Readback rejected')
            final = observed['experiment_validated']
            if final['macro_sha256'] != manifest['macro_sha256'] or final['checks_sha256'] != manifest['checks_sha256']:
                raise RuntimeError('Source/check binding failed')
            for key, name in [('model', 'RESULT.CATPart'), ('image', 'RESULT.jpg')]:
                if Path(final[key]).resolve() != (folder / name).resolve() or sha((folder / name).read_bytes()) != final[key + '_sha256']:
                    raise RuntimeError('Output binding failed')
            result = {'job_id': job_id, 'source': 'OpenCode_MCP_live_CSharp_STA', 'requirement': manifest['requirement'],
                      'macro_sha256': manifest['macro_sha256'], 'approval_origin': manifest['approval_origin'],
                      'readback': observed['independent_readback'], 'reopened_readback': observed['reopened_readback'],
                      'final': final, 'cached_no_CAD_dispatch': False, 'no_automatic_retry': True,
                      'interactive_approval_required': manifest.get('interactive_approval_required', True),
                      'limits': ['automatically executed macro, not sandboxed', 'checks are model-proposed; not a separate requirement oracle',
                                 'native feature/depth/volume checks are not full geometric equivalence or Class-A acceptance', 'GUI and unrelated automation are not locked']}
            (folder / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            self.finish(job_id, owner, result)
            return result
        except BaseException as error:
            try:
                self.finish(job_id, owner)
            except BaseException:
                pass
            (folder / 'failure.json').write_text(json.dumps({'type': type(error).__name__, 'gate': self.snapshot(),
                'completion': 'not accepted; CAD effects may exist; no replay or cleanup'}), encoding='utf-8')
            raise RuntimeError('CATIA执行未通过或结果未知，执行门已阻塞。请保留现场与证据，勿重新执行；中止不等于回滚。') from None

    def execute_request(self, request_id, requirement, macro_ascii, checks, summary=''):
        """Direct MCP route: prepare/reserve/run without any local approval record.

        A client request id binds one immutable request. Successful duplicate ids
        return cached results; running or uncertain requests are never replayed.
        """
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id):
            raise ValueError('request_id must be a stable 1-100 character identifier')
        if not isinstance(requirement, str) or not 1 <= len(requirement.strip()) <= 20000:
            raise ValueError('Missing or oversized modeling requirement')
        if not isinstance(summary, str):
            raise ValueError('summary must be text')
        proposal = {'summary': summary, 'macro_ascii': macro_ascii, 'checks': checks}
        job = 'native-' + sha((str(self.workspace) + '|' + request_id).encode())[:24]
        expected = sha(json.dumps(proposal, sort_keys=True, ensure_ascii=False).encode())
        with self._transaction() as db:
            existing = db.execute('SELECT * FROM native_ui_jobs WHERE job_id=?', (job,)).fetchone()
        if existing is not None:
            manifest = json.loads(existing['manifest_json'])
            if manifest['requirement'] != requirement or manifest.get('proposal_sha256') != expected:
                raise ValueError('request_id already belongs to different input; no dispatch')
            if existing['state'] not in ('SUCCEEDED', 'FAILED'):
                raise GateBlocked('Request already submitted or uncertain; no replay')
            return {**json.loads(existing['result_json']), 'cached_no_CAD_dispatch': True}
        manifest = self.prepare(requirement, proposal, expected, job_id=job)
        self.reserve(manifest['job_id'])
        return self.run(manifest['job_id'], macro_ascii)
