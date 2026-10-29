"""Task ledger and Bilibili experiences; never a store of user chat transcripts."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, operation TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL UNIQUE, scope TEXT NOT NULL, origin TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL)')
            db.execute("UPDATE tasks SET state='interrupted' WHERE state='running'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, scope, operation, target):
        with self.connect() as db:
            return db.execute('INSERT INTO tasks(scope,operation,target,state,created) VALUES(?,?,?,?,?)',
                              (scope, operation, target, 'running', datetime.now(timezone.utc).isoformat())).lastrowid

    def finish(self, task_id, scope, payload):
        with self.connect() as db:
            row = db.execute('SELECT state FROM tasks WHERE id=? AND scope=?', (task_id, scope)).fetchone()
            if not row or row['state'] != 'running':
                raise ValueError('task ownership/state mismatch')
            db.execute('INSERT INTO reports(task_id,scope,origin,payload,created) VALUES(?,?,?,?,?)',
                       (task_id, scope, 'bilibili_shadow', json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            db.execute("UPDATE tasks SET state='complete' WHERE id=?", (task_id,))

    def fail(self, task_id, scope):
        with self.connect() as db:
            db.execute("UPDATE tasks SET state='failed' WHERE id=? AND scope=? AND state='running'", (task_id, scope))

    def recent(self, scope, limit=3):
        with self.connect() as db:
            rows = db.execute('SELECT task_id,origin,payload,created FROM reports WHERE scope=? ORDER BY id DESC LIMIT ?', (scope, min(5, max(1, limit)))).fetchall()
            return [{'task_id':r['task_id'], 'origin':r['origin'], 'created':r['created'], 'report':json.loads(r['payload'])} for r in rows]
