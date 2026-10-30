"""Fail-closed candidate gate for cooperating local services sharing ONE SQLite path.

No lease expiry, dead-PID unlock or remote recovery API. This does not lock CATIA's
GUI, unrelated automation clients or services configured with a different database.
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class GateBlocked(RuntimeError):
    pass


class GateOwnershipError(RuntimeError):
    pass


class GateBusy(RuntimeError):
    """Database contention; does not imply whether any prior CAD call completed."""
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


class SessionGate:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS gate (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                status TEXT NOT NULL CHECK(status IN ('IDLE','RUNNING','FROZEN')),
                owner TEXT, operation TEXT, pid INTEGER, updated_at TEXT NOT NULL,
                CHECK ((status='IDLE' AND owner IS NULL) OR
                       (status IN ('RUNNING','FROZEN') AND owner IS NOT NULL)))''')
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL, kind TEXT NOT NULL, owner TEXT,
                detail_json TEXT NOT NULL)''')
            db.execute("INSERT OR IGNORE INTO gate VALUES (1,'IDLE',NULL,NULL,NULL,?)", (utc(),))

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.OperationalError as error:
            db.rollback()
            code = getattr(error, 'sqlite_errorcode', 0) & 0xff
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise GateBusy('GATE_DATABASE_BUSY: execution state is unconfirmed; '
                               'do not infer CAD failure or resend a CAD operation. '
                               'Inspect the gate after database contention clears.') from error
            raise
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, kind, owner, detail):
        db.execute('INSERT INTO events(at,kind,owner,detail_json) VALUES (?,?,?,?)',
                   (utc(), kind, owner, json.dumps(detail, ensure_ascii=False)))

    def acquire(self, operation):
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError('operation must be nonempty')
        token = str(uuid.uuid4())
        with self._transaction() as db:
            row = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row['status'] != 'IDLE':
                raise GateBlocked('GATE_' + row['status'] + ': CATIA candidate gate is ' + row['status'] +
                                  '; no dispatch. Reconciliation is required for orphaned/uncertain work.')
            db.execute("UPDATE gate SET status='RUNNING',owner=?,operation=?,pid=?,updated_at=? WHERE singleton=1",
                       (token, operation, os.getpid(), utc()))
            self._event(db, 'acquired', token, {'operation': operation, 'pid': os.getpid()})
        return token

    def complete(self, token, evidence):
        """Called only after the trusted local service directly observes completion.

        Evidence here is service-provided audit context, not a validated RunRecord.
        The method is never exposed to an agent as a tool.
        """
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError('Completion needs local observation evidence')
        with self._transaction() as db:
            row = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row['status'] != 'RUNNING' or row['owner'] != token:
                raise GateOwnershipError('Only the running owner can complete; frozen work requires reconciliation')
            self._event(db, 'completed', token, evidence)
            db.execute("UPDATE gate SET status='IDLE',owner=NULL,operation=NULL,pid=NULL,updated_at=? WHERE singleton=1", (utc(),))

    def freeze(self, token, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Freeze needs a reason')
        with self._transaction() as db:
            row = db.execute('SELECT * FROM gate WHERE singleton=1').fetchone()
            if row['status'] != 'RUNNING' or row['owner'] != token:
                raise GateOwnershipError('Only the running owner can freeze')
            db.execute("UPDATE gate SET status='FROZEN',updated_at=? WHERE singleton=1", (utc(),))
            self._event(db, 'frozen', token, {'reason': reason})

    def snapshot(self):
        with self._transaction() as db:
            row = dict(db.execute('SELECT * FROM gate WHERE singleton=1').fetchone())
            # Owner tokens are internal and not returned by the MCP status tool.
            row.pop('owner')
            return row

    def events(self):
        with self._transaction() as db:
            rows = db.execute('SELECT seq,at,kind,detail_json FROM events ORDER BY seq').fetchall()
            return [dict(row) for row in rows]
