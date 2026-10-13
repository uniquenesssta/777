"""Durable auxiliary output queue; ledger-v1 remains the financial authority."""
import base64
from contextlib import contextmanager, closing
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
import uuid

from quote_ledger.paths import local_path, Conflict
from quote_ledger.store import encoded, identifier, now
from .protocol import APIError
from .output_render import FORMAT, KINDS, MAX_BYTES, public_order, render, validate, payload_hash

DDL = (
    'CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), format TEXT NOT NULL, ledger_id TEXT NOT NULL) STRICT',
    "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, role TEXT NOT NULL, order_id TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('queued','running','failed','done')), attempts INTEGER NOT NULL, error TEXT, blob_sha256 TEXT, size INTEGER, output_path TEXT, settings_revision INTEGER, created_at TEXT NOT NULL) STRICT",
    'CREATE TABLE receipts (request_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL) STRICT',
    'CREATE TABLE events (sequence INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), operation TEXT NOT NULL, actor_id TEXT NOT NULL, at TEXT NOT NULL) STRICT',
    'CREATE INDEX jobs_state_created ON jobs(state,created_at,job_id)',
    "CREATE TRIGGER payload_immutable BEFORE UPDATE OF job_id,actor_id,role,order_id,kind,payload_json,payload_sha256,created_at ON jobs BEGIN SELECT RAISE(ABORT,'OUTPUT_SNAPSHOT_IMMUTABLE'); END",
)
for table in ('receipts', 'events'):
    for op in ('UPDATE', 'DELETE'):
        DDL += (f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'OUTPUT_APPEND_ONLY'); END",)


def signature(c):
    return hashlib.sha256(encoded([list(row) for row in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]).encode()).hexdigest()


@lru_cache(maxsize=1)
def expected_signature():
    with closing(sqlite3.connect(':memory:')) as c:
        for sql in DDL: c.execute(sql)
        return signature(c)


class Outputs:
    def __init__(self, path, ledger_id):
        self.path = local_path(path); self.ledger_id = ledger_id
        self._lock = threading.RLock(); self._worker = threading.Lock()
        with self.connection(): pass

    @classmethod
    def create(cls, path, ledger_id):
        path = local_path(path, exists=False)
        folder=local_path(path.parent/'output-blobs',directory=True,exists=False)
        if folder.exists():raise FileExistsError('Existing output directory is not adopted')
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar=local_path(path.with_name(path.name+suffix),exists=False)
            if sidecar.exists(): raise FileExistsError('Existing output sidecar')
        fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600); os.close(fd)
        with closing(sqlite3.connect(path)) as c:
            c.execute('PRAGMA foreign_keys=ON')
            for sql in DDL: c.execute(sql)
            c.execute('INSERT INTO meta VALUES(1,?,?)', ('777-output-store-v1', ledger_id))
            c.execute('PRAGMA application_id=926365519'); c.execute('PRAGMA user_version=1'); c.commit()
        folder.mkdir(mode=0o700)
        return cls(path, ledger_id)

    @contextmanager
    def connection(self, readonly=False):
        path = local_path(self.path)
        for suffix in ('-wal', '-shm', '-journal'): local_path(path.with_name(path.name+suffix), exists=False)
        c = sqlite3.connect(path.as_uri()+('?mode=ro' if readonly else '?mode=rw'), uri=True, isolation_level=None, timeout=3)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA foreign_keys=ON')
            if readonly: c.execute('PRAGMA query_only=ON')
            else: c.execute('PRAGMA synchronous=FULL')
            row = c.execute('SELECT * FROM meta WHERE id=1').fetchone()
            if c.execute('PRAGMA application_id').fetchone()[0] != 926365519 or c.execute('PRAGMA user_version').fetchone()[0] != 1 or signature(c) != expected_signature() or not row or row['format'] != '777-output-store-v1' or row['ledger_id'] != self.ledger_id:
                raise APIError(503, 'OUTPUT_STORE_INCOMPATIBLE')
            yield c
        finally: c.close()

    def has_request(self, request_id):
        with self.connection(readonly=True) as c: return c.execute('SELECT 1 FROM receipts WHERE request_id=?', (request_id,)).fetchone() is not None

    def receipt(self, actor, request_id, fingerprint=None):
        identifier(request_id)
        with self.connection(readonly=True) as c: row = c.execute('SELECT * FROM receipts WHERE request_id=?', (request_id,)).fetchone()
        if row is None: return None
        if actor.role != 'admin' and row['actor_id'] != actor.subject: raise APIError(404, 'NOT_FOUND')
        if fingerprint is not None and row['fingerprint'] != fingerprint: raise Conflict('Output request payload changed')
        result=json.loads(row['result_json'])
        if result.get('kind')=='excel_admin' and actor.role!='admin':raise APIError(404,'NOT_FOUND')
        return result

    def enqueue(self, actor, data, order):
        key = identifier(data['request_id']); fingerprint = payload_hash({'actor': actor.subject, 'role': actor.role, **data})
        with self._lock, self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM receipts WHERE request_id=?', (key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint: raise Conflict('Output request payload changed')
                c.execute('ROLLBACK'); return json.loads(old['result_json'])
            if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= 64: raise APIError(429, 'OUTPUT_QUEUE_FULL')
            value = order if data['kind'] == 'excel_admin' else public_order(order)
            payload = {'format': FORMAT, 'job_id': key, 'kind': data['kind'], 'order': value}
            raw = encoded(payload)
            if len(raw.encode()) > 2*1024*1024: raise APIError(413, 'OUTPUT_SNAPSHOT_TOO_LARGE')
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,\'queued\',0,NULL,NULL,NULL,NULL,NULL,?)',
                      (key, actor.subject, actor.role, order['order_id'], data['kind'], raw, payload_hash(payload), now()))
            receipt = {'request_id': key, 'job_id': key, 'order_id': order['order_id'], 'order_revision': order['revision'], 'kind': data['kind'], 'format': FORMAT, 'state': 'queued'}
            c.execute('INSERT INTO receipts VALUES(?,?,?,?)', (key, actor.subject, fingerprint, encoded(receipt)))
            c.execute('INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,?,?,?)', (key, 'enqueue', actor.subject, now()))
            c.execute('COMMIT'); return receipt

    def _job(self, c, actor, key):
        identifier(key); row = c.execute('SELECT * FROM jobs WHERE job_id=?', (key,)).fetchone()
        if row is None or actor.role != 'admin' and row['actor_id'] != actor.subject or row['kind'] == 'excel_admin' and actor.role != 'admin': raise APIError(404, 'NOT_FOUND')
        return row

    @staticmethod
    def project(row):
        return {k: row[k] for k in ('job_id', 'order_id', 'kind', 'state', 'attempts', 'error', 'blob_sha256', 'size', 'created_at')} | {'format': FORMAT}

    def status(self, actor, key):
        with self.connection(readonly=True) as c: return self.project(self._job(c, actor, key))

    def listing(self, actor):
        with self.connection(readonly=True) as c:
            rows = c.execute('SELECT * FROM jobs'+('' if actor.role == 'admin' else " WHERE actor_id=? AND kind!='excel_admin'")+ ' ORDER BY created_at DESC,job_id DESC LIMIT 100', () if actor.role == 'admin' else (actor.subject,))
            return {'jobs': [self.project(row) for row in rows], 'limit': 100, 'format': FORMAT}

    def retry(self, actor, key, request_id):
        identifier(request_id); fp = payload_hash({'actor': actor.subject, 'job_id': key, 'operation': 'retry'})
        with self._lock, self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); row = self._job(c, actor, key)
            old = c.execute('SELECT * FROM receipts WHERE request_id=?', (request_id,)).fetchone()
            if old:
                if old['fingerprint'] != fp: raise Conflict('Output retry changed')
                c.execute('ROLLBACK'); return json.loads(old['result_json'])
            if row['state'] == 'running': raise APIError(409, 'OUTPUT_ALREADY_RUNNING')
            if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= 64: raise APIError(429, 'OUTPUT_QUEUE_FULL')
            c.execute("UPDATE jobs SET state='queued',error=NULL WHERE job_id=?", (key,))
            result = {'request_id': request_id, 'job_id': key, 'order_id': row['order_id'], 'state': 'queued', 'format': FORMAT}
            c.execute('INSERT INTO receipts VALUES(?,?,?,?)', (request_id, actor.subject, fp, encoded(result)))
            c.execute('INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,?,?,?)', (key, 'retry', actor.subject, now()))
            c.execute('COMMIT'); return result

    def blob_path(self, row):
        identifier(row['job_id'])
        if row['kind'] not in KINDS:raise APIError(503,'OUTPUT_BLOB_INVALID')
        return local_path(self.path.parent/'output-blobs', directory=True)/ (row['job_id']+KINDS[row['kind']])

    def _blob(self, row):
        path = local_path(self.blob_path(row))
        if path.stat().st_size>MAX_BYTES:raise APIError(503,'OUTPUT_BLOB_CHANGED')
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES or row['blob_sha256'] is not None and hashlib.sha256(raw).hexdigest() != row['blob_sha256']: raise APIError(503, 'OUTPUT_BLOB_CHANGED')
        payload = json.loads(row['payload_json'])
        if payload_hash(payload) != row['payload_sha256']: raise APIError(503, 'OUTPUT_SNAPSHOT_CHANGED')
        validate(raw, payload); return raw

    def content(self, actor, key):
        with self.connection(readonly=True) as c: row = self._job(c, actor, key)
        if row['blob_sha256'] is None: raise APIError(409, 'OUTPUT_NOT_RENDERED')
        raw = self._blob(row)
        return {'job_id': key, 'format': FORMAT, 'filename': key+KINDS[row['kind']], 'size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'data_base64': base64.b64encode(raw).decode(),
                'media_type': 'image/png' if row['kind'] == 'quote_png' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}

    def recover(self):
        # Called only by the single host owner at startup, never by a reader.
        with self._lock, self.connection() as c:
            c.execute("UPDATE jobs SET state='queued',error='OUTPUT_RESTART_RECOVERY' WHERE state='running'")

    def run_one(self, service, *, fault=None):
        if not self._worker.acquire(blocking=False): return False
        try:
            with self._lock, self.connection() as c:
                c.execute('BEGIN IMMEDIATE')
                row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at,job_id LIMIT 1").fetchone()
                if row is None: c.execute('ROLLBACK'); return False
                key = row['job_id']; c.execute("UPDATE jobs SET state='running',attempts=attempts+1,error=NULL WHERE job_id=?", (key,)); c.execute('COMMIT')
            try:
                with service.auth._lock, service.auth.connection() as c:
                    user = c.execute('SELECT role,enabled FROM users WHERE id=?', (row['actor_id'],)).fetchone()
                    if not user or not user['enabled'] or user['role'] != row['role']: raise APIError(403, 'OUTPUT_ACCOUNT_CHANGED')
                    preferences = service.auth.preferences()
                path = self.blob_path(row)
                if path.exists(): raw = self._blob(row)
                else:
                    payload = json.loads(row['payload_json'])
                    if payload_hash(payload) != row['payload_sha256']: raise APIError(503, 'OUTPUT_SNAPSHOT_CHANGED')
                    raw = render(payload)
                    temporary=path.with_name('.'+path.name+'.'+str(uuid.uuid4())+'.partial')
                    try:
                        fd = os.open(temporary, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
                        with os.fdopen(fd, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                        if os.name=='nt':os.rename(temporary,path)
                        else:os.link(temporary,path)
                    finally:
                        try:temporary.unlink()
                        except FileNotFoundError:pass
                sha = hashlib.sha256(raw).hexdigest()
                with self._lock, self.connection() as c:
                    c.execute('UPDATE jobs SET blob_sha256=?,size=? WHERE job_id=?', (sha, len(raw), key))
                if fault: fault('rendered')
                if row['kind'] == 'excel_admin': target = path
                else:
                    directory = preferences['image_dir' if row['kind'] == 'quote_png' else 'export_dir']
                    if not directory: raise APIError(409, 'OUTPUT_DIRECTORY_NOT_PUBLISHED')
                    target = publish(path, directory, '777-'+row['order_id']+'-'+key+KINDS[row['kind']], sha)
                if fault: fault('published')
                with self._lock, self.connection() as c:
                    c.execute('BEGIN IMMEDIATE')
                    c.execute("UPDATE jobs SET state='done',error=NULL,output_path=?,settings_revision=? WHERE job_id=?", (str(target), preferences['revision'], key))
                    c.execute('INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,?,?,?)', (key, 'done', row['actor_id'], now()))
                    c.execute('COMMIT')
            except Exception as exc:
                code = exc.code if isinstance(exc, APIError) else 'OUTPUT_IO_FAILED:'+type(exc).__name__
                with self._lock, self.connection() as c: c.execute("UPDATE jobs SET state='failed',error=? WHERE job_id=?", (code, key))
            return True
        finally: self._worker.release()

    def backup(self, folder):
        with self._lock, self.connection(readonly=True) as origin, closing(sqlite3.connect(Path(folder)/'outputs.sqlite3')) as target:
            origin.backup(target); target.commit()
        snapshot = Outputs(Path(folder)/'outputs.sqlite3', self.ledger_id)
        (Path(folder)/'output-blobs').mkdir(mode=0o700)
        with snapshot.connection(readonly=True) as c:
            for row in c.execute('SELECT * FROM jobs WHERE blob_sha256 IS NOT NULL'):
                raw = self._blob(row); destination = Path(folder)/'output-blobs'/self.blob_path(row).name
                with open(destination, 'xb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        with open(Path(folder)/'outputs.sqlite3', 'r+b') as stream: os.fsync(stream.fileno())

    def validate_ledger(self, ledger):
        with self.connection(readonly=True) as c, ledger.connection(readonly=True) as l:
            for row in c.execute('SELECT * FROM jobs'):
                payload=json.loads(row['payload_json']);order=payload.get('order',{})
                original=l.execute('SELECT * FROM orders WHERE order_id=?',(row['order_id'],)).fetchone()
                if payload_hash(payload)!=row['payload_sha256'] or payload.get('format')!=FORMAT or payload.get('job_id')!=row['job_id'] or payload.get('kind')!=row['kind'] or row['kind'] not in KINDS or not original or original['revision']<order.get('revision',1) or str(original['income_cents'])!=order.get('income_cents') or json.loads(original['details_json'])!=order.get('details'):
                    raise APIError(503,'OUTPUT_LEDGER_BINDING_INVALID')
                if row['kind']=='excel_admin' and (row['role']!='admin' or any(str(original[k])!=order.get(k) for k in ('cost_cents','profit_cents'))):raise APIError(503,'OUTPUT_LEDGER_BINDING_INVALID')
                if row['blob_sha256'] is not None:self._blob(row)


def publish(source, directory, filename, expected_sha):
    root = Path(directory)
    if not root.is_absolute(): raise APIError(422, 'OUTPUT_DIRECTORY_INVALID')
    for p in (root, *root.parents):
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)&0x400 or not stat.S_ISDIR(info.st_mode): raise APIError(422, 'OUTPUT_DIRECTORY_UNSAFE')
    target = root/filename
    def same():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0)&0x400 or info.st_size > MAX_BYTES: raise APIError(409, 'OUTPUT_FILE_CONFLICT')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha: raise APIError(409, 'OUTPUT_FILE_CONFLICT')
    if target.exists(): same(); return target
    temporary = root/('.777-output-'+str(uuid.uuid4())+'.partial')
    try:
        with open(temporary, 'xb') as stream:
            with open(source, 'rb') as origin: copy_output(origin, stream)
            stream.flush(); os.fsync(stream.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_sha: raise APIError(503, 'OUTPUT_COPY_CHANGED')
        try:
            if os.name == 'nt': os.rename(temporary, target)
            else: os.link(temporary, target)  # Exclusive final publish, never replace.
        except FileExistsError: same()
        same(); return target
    finally:
        try: temporary.unlink()
        except FileNotFoundError: pass


def copy_output(origin, stream):
    shutil.copyfileobj(origin, stream)
