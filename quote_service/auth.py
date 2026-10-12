"""Host-local scrypt accounts and durable hashed, revocable bearer sessions."""
from contextlib import contextmanager,closing
from functools import lru_cache
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid

from quote_ledger import Principal
from quote_ledger.paths import local_path
from quote_ledger.schema import signature
from .protocol import APIError, text

APPLICATION_ID = 0x37373741
DDL = (
    'CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, role TEXT NOT NULL CHECK(role IN (\'admin\',\'sales\')), salt BLOB NOT NULL, verifier BLOB NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), epoch INTEGER NOT NULL) STRICT',
    'CREATE TABLE sessions (digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), epoch INTEGER NOT NULL, expires INTEGER NOT NULL) STRICT',
    'CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, export_dir TEXT NOT NULL, image_dir TEXT NOT NULL) STRICT',
    'CREATE TABLE auth_audit (sequence INTEGER PRIMARY KEY, actor TEXT NOT NULL, operation TEXT NOT NULL, target TEXT NOT NULL, at INTEGER NOT NULL) STRICT',
    'CREATE TABLE backup_plan (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, interval_minutes INTEGER NOT NULL, daily_hour INTEGER NOT NULL, rolling INTEGER NOT NULL, daily INTEGER NOT NULL, offset_minutes INTEGER NOT NULL) STRICT',
    'CREATE TABLE backup_health (id INTEGER PRIMARY KEY CHECK(id=1), last_success_json TEXT, error TEXT, at INTEGER NOT NULL) STRICT',
)


@lru_cache(maxsize=1)
def schema_signature():
    with closing(sqlite3.connect(':memory:')) as c:
        for sql in DDL:c.execute(sql)
        return signature(c)


def password(value):
    text(value, 128)
    if len(value) < 12 or len(value.encode('utf-8')) > 512:
        raise APIError(422, 'PASSWORD_LENGTH_12_TO_128')
    return value


def username(value):
    value = text(value, 64, nonempty=True)
    if value.strip() != value or len(value) < 3 or any(ord(c) < 32 for c in value):
        raise APIError(422, 'INVALID_USERNAME')
    return value.casefold()


def verifier(value, salt):
    return hashlib.scrypt(value.encode('utf-8'), salt=salt, n=32768, r=8, p=1, maxmem=64*1024*1024, dklen=32)


class Auth:
    def __init__(self, path, *, clock=time.time, ttl=28800):
        self.path = local_path(path)
        self.clock, self.ttl = clock, ttl
        self._lock = threading.RLock()
        self._attempts = {}
        with self.connection():
            pass

    @classmethod
    def create(cls, path, user, secret):
        path = local_path(path, exists=False)
        user, secret = username(user), password(secret)
        fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600);os.close(fd)
        c = sqlite3.connect(path)
        try:
            with c:
                for sql in DDL:c.execute(sql)
                c.execute(f'PRAGMA application_id={APPLICATION_ID}')
                c.execute('PRAGMA user_version=1')
                salt=secrets.token_bytes(16)
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,1,1)', (str(uuid.uuid4()), user, 'admin', salt, verifier(secret,salt)))
                c.execute("INSERT INTO preferences VALUES(1,1,'','')")
                c.execute('INSERT INTO backup_plan VALUES(1,1,30,2,48,30,480)')
                c.execute('INSERT INTO backup_health VALUES(1,NULL,NULL,0)')
        finally:c.close()
        return cls(path)

    @contextmanager
    def connection(self):
        local_path(self.path)
        c = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=3, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA synchronous=FULL')
            if c.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or c.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise APIError(503, 'AUTH_SCHEMA_INVALID')
            if signature(c)!=schema_signature():
                raise APIError(503, 'AUTH_SCHEMA_INVALID')
            yield c
        finally:c.close()

    def login(self, user, secret, peer):
        user = username(user);text(secret,128)
        if len(secret.encode('utf-8'))>512:raise APIError(401,'UNAUTHENTICATED')
        now=int(self.clock());key=(str(peer),user);peer_key=(str(peer),'*')
        with self._lock:
            self._attempts={k:v for k,v in self._attempts.items() if now-v[1]<300}
            attempt=self._attempts.get(key,(0,now))
            peer_attempt=self._attempts.get(peer_key,(0,now))
            if attempt[0]>=5 or peer_attempt[0]>=20 or len(self._attempts)>=2048:raise APIError(429,'LOGIN_RATE_LIMIT')
            with self.connection() as c:
                row=c.execute('SELECT * FROM users WHERE username=?',(user,)).fetchone()
                salt=row['salt'] if row else b'777-no-such-user!'
                expected=row['verifier'] if row else bytes(32)
                valid=hmac.compare_digest(verifier(secret,salt),expected)
                if not valid or not row or not row['enabled']:
                    self._attempts[key]=(attempt[0]+1,attempt[1]);self._attempts[peer_key]=(peer_attempt[0]+1,peer_attempt[1]);raise APIError(401,'UNAUTHENTICATED')
                token=secrets.token_urlsafe(32)
                c.execute('BEGIN IMMEDIATE')
                try:
                    current=c.execute('SELECT enabled,epoch FROM users WHERE id=?',(row['id'],)).fetchone()
                    if not current['enabled'] or current['epoch']!=row['epoch']:raise APIError(401,'UNAUTHENTICATED')
                    c.execute('DELETE FROM sessions WHERE expires<=?',(now,))
                    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],row['epoch'],now+self.ttl))
                    c.execute('COMMIT')
                except BaseException:c.execute('ROLLBACK');raise
                self._attempts.pop(key,None)
                return {'token':token,'expires':now+self.ttl,'subject':row['id'],'role':row['role']}

    def authenticate(self, token):
        if type(token) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',token):raise APIError(401,'UNAUTHENTICATED')
        with self.connection() as c:
            row=c.execute('SELECT u.id,u.role,u.enabled,u.epoch,s.epoch AS session_epoch,s.expires FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.digest=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if row is None or not row['enabled'] or row['epoch']!=row['session_epoch'] or row['expires']<=int(self.clock()):raise APIError(401,'UNAUTHENTICATED')
            return Principal(row['id'],row['role'])

    def logout(self, token):
        with self.connection() as c:c.execute('DELETE FROM sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))

    @staticmethod
    def admin(actor):
        if actor.role!='admin':raise APIError(403,'FORBIDDEN')

    def accounts(self, actor):
        self.admin(actor)
        with self.connection() as c:return [dict(r) for r in c.execute('SELECT id,username,role,enabled,epoch FROM users ORDER BY username')]

    def create_account(self, actor, user, secret, role):
        self.admin(actor);user=username(user);secret=password(secret)
        if role not in ('admin','sales'):raise APIError(422,'INVALID_ROLE')
        salt=secrets.token_bytes(16);hashed=verifier(secret,salt);identifier=str(uuid.uuid4())
        with self._lock,self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,1,1)',(identifier,user,role,salt,hashed))
                c.execute('INSERT INTO auth_audit(actor,operation,target,at) VALUES(?,?,?,?)',(actor.subject,'account_created',identifier,int(self.clock())))
                c.execute('COMMIT')
            except BaseException:c.execute('ROLLBACK');raise
        return {'id':identifier,'username':user,'role':role}

    def update_account(self, actor, identifier, *, secret=None, role=None, enabled=None):
        self.admin(actor)
        if role is not None and role not in ('admin','sales') or enabled is not None and type(enabled) is not bool:raise APIError(422,'INVALID_ACCOUNT')
        salt=secrets.token_bytes(16) if secret is not None else None
        hashed=verifier(password(secret),salt) if salt else None
        with self._lock,self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                row=c.execute('SELECT * FROM users WHERE id=?',(identifier,)).fetchone()
                if row is None:raise APIError(404,'NOT_FOUND')
                next_role=role or row['role'];next_enabled=row['enabled'] if enabled is None else int(enabled)
                if row['role']=='admin' and row['enabled'] and (next_role!='admin' or not next_enabled) and c.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]<=1:raise APIError(409,'LAST_ADMIN_REQUIRED')
                c.execute('UPDATE users SET role=?,enabled=?,salt=?,verifier=?,epoch=epoch+1 WHERE id=?',(next_role,next_enabled,salt or row['salt'],hashed or row['verifier'],identifier))
                c.execute('DELETE FROM sessions WHERE user_id=?',(identifier,))
                c.execute('INSERT INTO auth_audit(actor,operation,target,at) VALUES(?,?,?,?)',(actor.subject,'account_updated',identifier,int(self.clock())))
                c.execute('COMMIT')
            except BaseException:c.execute('ROLLBACK');raise
        return {'id':identifier,'role':next_role,'enabled':bool(next_enabled)}

    def preferences(self):
        with self.connection() as c:return dict(c.execute('SELECT revision,export_dir,image_dir FROM preferences WHERE id=1').fetchone())

    def save_preferences(self, actor, revision, export_dir, image_dir):
        self.admin(actor)
        if type(revision) is not int:raise APIError(422,'INVALID_REVISION')
        import ntpath
        def directory(value):
            value=text(value,32767,nonempty=True).strip()
            if any(ord(c)<32 for c in value):raise APIError(422,'INVALID_PUBLISHED_DIRECTORY')
            if os.name=='nt':
                drive,tail=ntpath.splitdrive(value)
                if not drive.startswith('\\\\') or drive.startswith(('\\\\?\\','\\\\.\\')) or len(drive[2:].split('\\'))!=2 or not all(drive[2:].split('\\')):raise APIError(422,'PUBLISHED_DIRECTORY_REQUIRES_UNC')
                if any(c in value for c in '*?:<>|"'):raise APIError(422,'INVALID_PUBLISHED_DIRECTORY')
                return ntpath.normpath(value)
            if not os.path.isabs(value):raise APIError(422,'INVALID_PUBLISHED_DIRECTORY')
            return os.path.normpath(value)
        export_dir=directory(export_dir);image_dir=directory(image_dir)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                if c.execute('SELECT revision FROM preferences WHERE id=1').fetchone()[0]!=revision:raise APIError(409,'SETTINGS_REVISION_CONFLICT')
                c.execute('UPDATE preferences SET revision=revision+1,export_dir=?,image_dir=? WHERE id=1',(export_dir,image_dir))
                c.execute('INSERT INTO auth_audit(actor,operation,target,at) VALUES(?,?,?,?)',(actor.subject,'directories_published','preferences',int(self.clock())))
                c.execute('COMMIT')
            except BaseException:c.execute('ROLLBACK');raise
        return self.preferences()

    def backup_plan(self):
        with self.connection() as c:return dict(c.execute('SELECT revision,interval_minutes,daily_hour,rolling,daily,offset_minutes FROM backup_plan WHERE id=1').fetchone())

    def save_backup_plan(self,actor,value):
        self.admin(actor)
        ranges={'revision':(1,2**63-2),'interval_minutes':(1,1440),'daily_hour':(0,23),'rolling':(1,512),'daily':(1,366),'offset_minutes':(-720,840)}
        if value.keys()!=ranges.keys() or any(type(value[k]) is not int or not a<=value[k]<=b for k,(a,b) in ranges.items()):raise APIError(422,'INVALID_BACKUP_PLAN')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                if c.execute('SELECT revision FROM backup_plan WHERE id=1').fetchone()[0]!=value['revision']:raise APIError(409,'SETTINGS_REVISION_CONFLICT')
                c.execute('UPDATE backup_plan SET revision=revision+1,interval_minutes=?,daily_hour=?,rolling=?,daily=?,offset_minutes=? WHERE id=1',tuple(value[k] for k in ('interval_minutes','daily_hour','rolling','daily','offset_minutes')))
                c.execute('INSERT INTO auth_audit(actor,operation,target,at) VALUES(?,?,?,?)',(actor.subject,'backup_plan_published','backup_plan',int(self.clock())))
                c.execute('COMMIT')
            except BaseException:c.execute('ROLLBACK');raise
        return self.backup_plan()

    def backup_health(self):
        with self.connection() as c:
            row=c.execute('SELECT * FROM backup_health WHERE id=1').fetchone()
            return {'last_success':json.loads(row['last_success_json']) if row['last_success_json'] else None,'error':row['error'],'at':row['at']}

    def record_backup_health(self,*,success=None,error=None):
        with self.connection() as c:
            if success is None:c.execute('UPDATE backup_health SET error=?,at=? WHERE id=1',(error,int(self.clock())))
            else:c.execute('UPDATE backup_health SET last_success_json=?,error=?,at=? WHERE id=1',(json.dumps(success),error,int(self.clock())))
