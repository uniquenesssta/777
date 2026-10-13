"""Private native ledger adapter. Existing authenticated HTTPS owns principals.

Only Rust writes the real financial database. Python read projections and legacy
format planning remain; the latter writes an in-memory preview, never the ledger.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from quote_core import (Amounts, CalculatedLine, DiscountLine, NormalLine, PriceItem, PriceSnapshot,
    QuoteSnapshot, DraftDetails, QuoteResult, Issue)
from quote_ledger.store import Ledger, Principal, require_admin, verify, encoded, inventory
from quote_ledger.paths import LedgerError, Conflict, Forbidden, InvalidDatabase, UnknownCommit, local_path

WORKER='rust-ledger-worker.exe'
NOTICES='rust-notices.txt'
RUST_FILES={WORKER,NOTICES}

def file_hash(path):
    h=hashlib.sha256()
    with open(local_path(path),'rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def snapshot_wire(snapshot):
    if type(snapshot) is not QuoteSnapshot:raise LedgerError('需要不可变报价')
    value=asdict(snapshot);value['lines']=list(value['lines'])
    for line in value['lines']:line['kind']=line.pop('line_kind')
    return value

def model_line(value):
    value=dict(value);kind=value.pop('kind')
    return NormalLine(**value) if kind=='normal' else DiscountLine(**value)

def result_model(value):
    def amount(a,discount=False):return Amounts(int(a['income_cents']),int(a['cost_cents']),discount)
    lines=None if value['lines'] is None else tuple(CalculatedLine(l['sequence'],model_line(l['raw']),
        None if l['price'] is None else PriceItem(**l['price']),tuple(tuple(p) for p in l['normalized']),
        amount(l['amounts'],l['raw']['kind']=='discount'),int(l['subtotal_before_cents'])) for l in value['lines'])
    return QuoteResult(value['status'],value['rule_version'],value['numeric_profile'],value['price_version_id'],
        lines,None if value['totals'] is None else amount(value['totals']),tuple(Issue(**i) for i in value['issues']),tuple(Issue(**i) for i in value['warnings']))

class RustLedger:
    backend='rust'
    def __init__(self,path,binary,*,auxiliary=False,expected_sha256=None,timeout=30,test_fault=None):
        if os.name=='nt' and auxiliary:raise LedgerError('Windows不能使用辅助平台模式')
        if os.name!='nt' and not auxiliary:raise LedgerError('需要实际Windows')
        self.path=local_path(path);self.binary=local_path(binary);self.auxiliary=auxiliary
        self.expected_sha256=expected_sha256;self.timeout=timeout;self.test_fault=test_fault;self.fault=None
        self._call({'op':'inventory'})
    @classmethod
    def create(cls,path,binary,*,auxiliary=False):
        # Native creation is exclusive. Use a temporary adapter without opening the absent DB.
        obj=object.__new__(cls);obj.path=local_path(path,exists=False);obj.binary=local_path(binary)
        obj.auxiliary=auxiliary;obj.expected_sha256=None;obj.timeout=30;obj.test_fault=None;obj.fault=None
        if os.name=='nt' and auxiliary or os.name!='nt' and not auxiliary:raise LedgerError('平台模式无效')
        obj._call({'op':'create'});return cls(path,binary,auxiliary=auxiliary)
    def _call(self,payload,*,timeout=None):
        try:local_path(self.binary)
        except LedgerError:raise InvalidDatabase('Rust执行文件不可用；不自动回退') from None
        if self.expected_sha256 is not None and file_hash(self.binary)!=self.expected_sha256:raise InvalidDatabase('Rust执行文件校验失败')
        args=[str(self.binary),str(self.path)]
        if self.auxiliary:args.append('--auxiliary')
        if self.test_fault:args.append('--test-fault='+self.test_fault)
        request_id=payload.get('request_id',payload.get('delta',{}).get('request_id'))
        try:
            p=subprocess.run(args,input=encoded(payload).encode('utf-8'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                timeout=self.timeout if timeout is None else timeout,check=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if p.returncode or len(p.stdout)>128*1024*1024:raise ValueError('native result unavailable')
            reply=json.loads(p.stdout)
            if type(reply) is not dict or type(reply.get('ok')) is not bool:raise ValueError('invalid native reply')
        except (OSError,ValueError,subprocess.TimeoutExpired):
            if request_id is not None:raise UnknownCommit(request_id) from None
            raise InvalidDatabase('Rust核心不可用；不自动回退') from None
        if not reply['ok']:
            code=reply.get('error')
            if code=='COMMIT_UNKNOWN' and request_id is not None:raise UnknownCommit(request_id)
            if code=='PRICES_NOT_PUBLISHED':
                from .protocol import APIError
                raise APIError(409,'PRICES_NOT_PUBLISHED')
            if code=='CONFLICT':raise Conflict('版本/请求冲突')
            if code=='FORBIDDEN':raise Forbidden('权限拒绝')
            if code=='BUSY':raise sqlite3.OperationalError('Rust账本忙')
            if code in {'INVALID_DATABASE','SCHEMA_SOURCE_MISMATCH','BACKUP_IO','RANDOM_UNAVAILABLE','LOCAL_PATH_REQUIRED','LOCAL_PATH_UNAVAILABLE','LINK_DISALLOWED','LINK_OR_TYPE_DISALLOWED','FIXED_DISK_REQUIRED'}:raise InvalidDatabase('Rust账本/快照不可用')
            if code=='EXISTS':raise FileExistsError('目标已存在，原件保留')
            raise LedgerError('Rust输入/路径无效：'+str(code))
        return reply['result']
    @contextmanager
    def connection(self,readonly=False):
        if not readonly:raise LedgerError('Rust后端禁止Python直接写真实账本')
        with Ledger(self.path).connection(readonly=True) as c:yield c
    def _owned_order(self,c,actor,order_id):return Ledger._owned_order(self,c,actor,order_id)
    @staticmethod
    def actor(actor):
        if type(actor) is not Principal:raise Forbidden('需要可信内部主体')
        return asdict(actor)
    def publish_prices(self,request_id,actor,prices,*,expected_price_version_id=None):
        require_admin(actor)
        if type(prices) is not PriceSnapshot:raise LedgerError('需要价格快照')
        return self._call(dict(op='publish_prices',request_id=request_id,actor=self.actor(actor),prices=asdict(prices),expected_price_version_id=expected_price_version_id))
    def submit_order(self,request_id,actor,snapshot,details=DraftDetails()):
        if type(details) is not DraftDetails:raise LedgerError('需要文本身份')
        return self._call(dict(op='submit_order',request_id=request_id,actor=self.actor(actor),snapshot=snapshot_wire(snapshot),details=asdict(details)))
    def append_note(self,request_id,actor,order_id,body,*,expected_revision):
        return self._call(dict(op='append_note',request_id=request_id,actor=self.actor(actor),order_id=order_id,body=body,expected_revision=expected_revision))
    def set_state(self,request_id,actor,order_id,state,reason,*,expected_revision):
        require_admin(actor)
        return self._call(dict(op='set_state',request_id=request_id,actor=self.actor(actor),order_id=order_id,state=state,reason=reason,expected_revision=expected_revision))
    def query_request(self,request_id,actor):return self._call(dict(op='query_request',request_id=request_id,actor=self.actor(actor)))
    def inventory(self):return self._call({'op':'inventory'})
    def active_prices(self):
        r=self._call({'op':'active_prices'});return PriceSnapshot(r['price_version_id'],tuple(PriceItem(**p) for p in r['items']))
    def calculate(self,snapshot):return result_model(self._call(dict(op='calculate',snapshot=snapshot_wire(snapshot))))
    def backup_snapshot(self,target,*,timeout=30):return self._call(dict(op='backup',target=str(local_path(target,exists=False))),timeout=timeout)
    def native_import(self,actor,owner_id,raw,kind,**kwargs):
        require_admin(actor)
        from quote_import.store import apply_source,verify_provenance
        tables=('orders','lines','notes','price_versions','import_batches','audit_events','requests')
        memory=sqlite3.connect(':memory:',isolation_level=None);memory.row_factory=sqlite3.Row
        try:
            with self.connection(readonly=True) as source:source.backup(memory)
            memory.execute('PRAGMA foreign_keys=ON');meta=verify(memory)
            before={t:{row[0] for row in memory.execute('SELECT * FROM '+t)} for t in tables}
            class Preview:
                fault=None
                @contextmanager
                def connection(self,readonly=False):yield memory
            result=apply_source(Preview(),actor,owner_id,raw,kind,**kwargs)
            verify_provenance(memory)
            delta=dict(request_id=result['request_id'],expected_revision=meta['revision'],result=result,
                final_inventory=inventory(memory),rows={t:[list(row) for row in memory.execute('SELECT * FROM '+t) if row[0] not in before[t]] for t in tables})
            return self._call(dict(op='import_apply',actor=self.actor(actor),delta=delta))
        finally:memory.close()
