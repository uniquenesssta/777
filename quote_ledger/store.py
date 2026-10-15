"""Transactional service-side ledger. Trusted principals are supplied by P05-02.

This module is not a network authentication boundary and is not wired to the
legacy clients. Every write recomputes through the existing quotation core.
"""
from contextlib import contextmanager
from quote_core.models import price_wire
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import uuid

from quote_core import (DiscountLine, DraftDetails, NormalLine, PriceSnapshot,
                        QuoteSnapshot, calculate_quote, parse_price_config)
from quote_core.numbers import NUMERIC_PROFILE, RULE_VERSION
from . import schema
from .paths import Conflict, Forbidden, InvalidDatabase, LedgerError, UnknownCommit, local_path


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def identifier(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:raise ValueError()
    except (ValueError, AttributeError):raise LedgerError('需要规范UUID') from None
    return value

def text(value, limit=256, required=False):
    if type(value) is not str or len(value)>limit or (required and not value.strip()):raise LedgerError('文本无效或超过范围')
    value.encode('utf-8')
    if '\x00' in value:raise LedgerError('文本包含NUL')
    return value


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    def __post_init__(self):
        text(self.subject,required=True)
        if self.role not in {'admin','sales'}:raise Forbidden('未知内部主体角色')


def require_admin(actor):
    if type(actor) is not Principal or actor.role != 'admin':raise Forbidden('需要管理员')


def verify(connection):
    if sqlite3.sqlite_version_info < (3,37,0):raise InvalidDatabase('需要SQLite3.37或更高版本')
    if (connection.execute('PRAGMA user_version').fetchone()[0] != schema.VERSION
            or connection.execute('PRAGMA application_id').fetchone()[0] != schema.APPLICATION_ID):
        raise InvalidDatabase('未知数据库/版本，原件保留；不自动覆盖')
    try:
        meta = connection.execute('SELECT * FROM ledger_meta WHERE singleton=1').fetchone()
        if not meta or meta['schema_version'] != schema.VERSION or meta['schema_hash'] != schema.expected_hash() or schema.signature(connection) != schema.expected_hash():
            raise InvalidDatabase('schema不兼容或被改变，原件保留')
    except sqlite3.DatabaseError as exc:raise InvalidDatabase('schema不可读，原件保留') from exc
    return meta


class Ledger:
    def __init__(self, path, *, fault=None, timeout=3):
        self.path = local_path(path)
        self.fault, self.timeout = fault, timeout
        with self.connection(readonly=True):pass

    @classmethod
    def create(cls, path):
        path = local_path(path,exists=False)
        for sidecar in (path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')):
            local_path(sidecar,exists=False)
            if sidecar.exists():raise FileExistsError('已有SQLite附属文件，原件保留')
        fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        connection = None
        try:
            connection = sqlite3.connect(path,isolation_level=None)
            connection.execute('PRAGMA foreign_keys=ON');connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL');connection.execute('BEGIN IMMEDIATE')
            for sql in schema.DDL:connection.execute(sql)
            connection.execute('INSERT INTO ledger_meta VALUES(1,?,?,?,?,NULL)',(schema.VERSION,schema.expected_hash(),str(uuid.uuid4()),0))
            connection.execute(f'PRAGMA application_id={schema.APPLICATION_ID}')
            connection.execute(f'PRAGMA user_version={schema.VERSION}');connection.execute('COMMIT')
        except BaseException:
            if connection is not None:connection.close();connection=None
            for leaf in (path,path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')):
                try:leaf.unlink()
                except FileNotFoundError:pass
            raise
        finally:
            if connection is not None:connection.close()
        return cls(path)

    @contextmanager
    def connection(self, readonly=False):
        path = local_path(self.path)
        for sidecar in (path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')):
            local_path(sidecar,exists=False)
        connection = sqlite3.connect(path.as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,
            timeout=self.timeout,isolation_level=None,autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            if readonly:connection.execute('PRAGMA query_only=ON')
            verify(connection)
            if not readonly:
                if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]!='wal':raise InvalidDatabase('WAL模式不可用')
                connection.execute('PRAGMA synchronous=FULL')
            yield connection
        finally:connection.close()

    def _write(self, request_id, actor, operation, payload, action):
        identifier(request_id)
        if type(actor) is not Principal:raise Forbidden('需要可信内部主体')
        fingerprint = digest(encoded({'actor':asdict(actor),'operation':operation,'payload':payload}))
        commit_attempted = False
        with self.connection() as connection:
            try:
                connection.execute('BEGIN IMMEDIATE')
                old = connection.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
                if old:
                    if old['fingerprint'] != fingerprint:raise Conflict('同request_id不同负载或主体')
                    connection.execute('ROLLBACK');return json.loads(old['result_json'])
                meta = verify(connection);revision = meta['revision']+1
                result, order_id, before = action(connection,revision)
                result = {**result,'request_id':request_id,'ledger_revision':revision}
                connection.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',
                    (request_id,actor.subject,fingerprint,operation,encoded(result),revision,now()))
                connection.execute('INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()),request_id,actor.subject,operation,order_id,encoded(before) if before is not None else None,encoded(result),now()))
                connection.execute('UPDATE ledger_meta SET revision=? WHERE singleton=1',(revision,))
                if self.fault:self.fault('before_commit',connection)
                commit_attempted = True;connection.execute('COMMIT')
                if self.fault:self.fault('after_commit',connection)
                return result
            except BaseException as exc:
                if connection.in_transaction:connection.execute('ROLLBACK')
                if commit_attempted:raise UnknownCommit(request_id) from exc
                raise

    def publish_prices(self, request_id, actor, prices, *, expected_price_version_id=None):
        require_admin(actor)
        if type(prices) is not PriceSnapshot:raise LedgerError('需要PriceSnapshot')
        text(prices.price_version_id,required=True)
        if expected_price_version_id is not None:text(expected_price_version_id,required=True)
        payload = {'items':[{**{k:v for k,v in price_wire(p).items() if k!='product_id'},'name':p.product_id} for p in prices.items]}
        canonical = encoded(payload)
        parsed = parse_price_config(canonical,price_version_id=prices.price_version_id)
        if parsed.status != 'ok':raise LedgerError('整份价格校验失败：'+','.join(i.reason for i in parsed.issues))
        for item,p in zip(payload['items'],parsed.config.prices.items):
            if p.pricing_mode=='cost_plus':item['sale']=p.sale
        canonical=encoded(payload)
        def action(c,revision):
            if verify(c)['active_price_id']!=expected_price_version_id:raise Conflict('当前发布价格已改变；请重新读取并确认')
            if c.execute('SELECT 1 FROM price_versions WHERE price_id=?',(prices.price_version_id,)).fetchone():raise Conflict('价格版本已存在且不可变')
            c.execute('INSERT INTO price_versions VALUES(?,?,?,?,?,?,?)',
                (prices.price_version_id,canonical,digest(canonical),RULE_VERSION,NUMERIC_PROFILE,actor.subject,now()))
            c.execute('UPDATE ledger_meta SET active_price_id=? WHERE singleton=1',(prices.price_version_id,))
            return {'price_version_id':prices.price_version_id},None,None
        return self._write(request_id,actor,'publish_prices',{'price_id':prices.price_version_id,'expected_price_version_id':expected_price_version_id,**payload},action)

    def submit_order(self, request_id, actor, snapshot, details=DraftDetails()):
        if type(snapshot) is not QuoteSnapshot or type(details) is not DraftDetails:raise LedgerError('需要不可变报价/身份快照')
        for value in asdict(details).values():text(value)
        payload = {'snapshot':asdict(snapshot),'details':asdict(details)}
        def action(c,revision):
            if snapshot.price_version_id != verify(c)['active_price_id']:raise Conflict('价格版本已更新；重算并确认后提交')
            row = c.execute('SELECT * FROM price_versions WHERE price_id=?',(snapshot.price_version_id,)).fetchone()
            if row is None or digest(row['payload_json']) != row['payload_sha256']:raise InvalidDatabase('价格快照损坏')
            prices = parse_price_config(row['payload_json'],price_version_id=row['price_id'])
            if prices.status!='ok':raise InvalidDatabase('价格快照校验失败')
            result = calculate_quote(snapshot,prices.config.prices)
            if result.status!='ok':raise LedgerError('报价无效：'+','.join(i.reason for i in result.issues))
            order_id = str(uuid.uuid4());totals=result.totals
            c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (order_id,actor.subject,snapshot.price_version_id,RULE_VERSION,NUMERIC_PROFILE,encoded(asdict(snapshot)),encoded(asdict(details)),totals.income_cents,totals.cost_cents,totals.profit_cents,'active',1,now(),request_id))
            for line in result.lines:
                c.execute('INSERT INTO lines VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()),order_id,line.sequence,line.raw.line_kind,encoded(asdict(line.raw)),encoded(dict(line.normalized)),encoded(price_wire(line.price)) if line.price else None,line.amounts.income_cents,line.amounts.cost_cents,line.amounts.profit_cents,line.subtotal_before_cents))
                if self.fault:self.fault('line_inserted',c)
            return {'order_id':order_id,'revision':1,**totals.cents_payload()},order_id,None
        return self._write(request_id,actor,'submit_order',payload,action)

    def _owned_order(self,c,actor,order_id):
        identifier(order_id)
        row = c.execute('SELECT * FROM orders WHERE order_id=?',(order_id,)).fetchone()
        if row is None:raise LedgerError('订单不存在')
        if actor.role!='admin' and row['owner_id']!=actor.subject:raise Forbidden('订单不属于当前主体')
        return row

    def append_note(self, request_id, actor, order_id, body, *, expected_revision):
        text(body,4096,True)
        if type(expected_revision) is not int or expected_revision<1:raise LedgerError('revision无效')
        def action(c,revision):
            row = self._owned_order(c,actor,order_id)
            if row['revision']!=expected_revision:raise Conflict('订单revision冲突')
            note_id=str(uuid.uuid4())
            c.execute('INSERT INTO notes VALUES(?,?,?,?,?,?)',(note_id,order_id,actor.subject,body,now(),request_id))
            c.execute('UPDATE orders SET revision=revision+1 WHERE order_id=?',(order_id,))
            return {'order_id':order_id,'note_id':note_id,'revision':expected_revision+1},order_id,{'revision':expected_revision}
        return self._write(request_id,actor,'append_note',{'order_id':order_id,'body':body,'expected_revision':expected_revision},action)

    def set_state(self, request_id, actor, order_id, state, reason, *, expected_revision):
        require_admin(actor);text(reason,4096,True)
        if state not in {'active','void'} or type(expected_revision) is not int or expected_revision<1:raise LedgerError('状态/revision无效')
        def action(c,revision):
            row=self._owned_order(c,actor,order_id)
            if row['revision']!=expected_revision:raise Conflict('订单revision冲突')
            if row['state']==state:raise Conflict('订单已是该状态')
            c.execute('UPDATE orders SET state=?,revision=revision+1 WHERE order_id=?',(state,order_id))
            return {'order_id':order_id,'state':state,'reason':reason,'revision':expected_revision+1},order_id,{'state':row['state'],'revision':row['revision']}
        return self._write(request_id,actor,'set_state',{'order_id':order_id,'state':state,'reason':reason,'expected_revision':expected_revision},action)

    def query_request(self, request_id, actor):
        identifier(request_id)
        if type(actor) is not Principal:raise Forbidden('需要可信内部主体')
        with self.connection(readonly=True) as c:
            row=c.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if row is None:return None
            if actor.role!='admin' and row['actor_id']!=actor.subject:raise Forbidden('请求不属于当前主体')
            return json.loads(row['result_json'])

    def inventory(self):
        with self.connection(readonly=True) as c:
            c.execute('BEGIN')
            return inventory(c)


def inventory(c):
    meta=verify(c)
    if c.execute('PRAGMA quick_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchall():raise InvalidDatabase('数据库完整性/外键核对失败')
    counts={table:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('orders','lines','notes','price_versions','import_batches','audit_events','requests')}
    if counts['requests']!=meta['revision'] or counts['audit_events']!=counts['requests']:
        raise InvalidDatabase('回执/审计/revision链不完整')
    prices={}
    for row in c.execute('SELECT * FROM price_versions'):
        parsed=parse_price_config(row['payload_json'],price_version_id=row['price_id'])
        if digest(row['payload_json'])!=row['payload_sha256'] or parsed.status!='ok' or row['rule_version']!=RULE_VERSION or row['numeric_profile']!=NUMERIC_PROFILE:
            raise InvalidDatabase('价格版本/内容核对失败')
        prices[row['price_id']]=parsed.config.prices
    totals=[0,0,0]
    for order in c.execute('SELECT * FROM orders'):
        try:
            raw=json.loads(order['input_json']);lines=[]
            for item in raw['lines']:
                item=dict(item);kind=item.pop('line_kind')
                lines.append(DiscountLine(**item) if kind=='discount' else NormalLine(**item) if kind=='normal' else None)
            snapshot=QuoteSnapshot(raw['price_version_id'],tuple(lines),raw['rule_version'],raw['numeric_profile'])
            calculated=calculate_quote(snapshot,prices[order['price_id']])
            if calculated.status!='ok':raise ValueError('计算失败')
            rows=c.execute('SELECT * FROM lines WHERE order_id=? ORDER BY sequence',(order['order_id'],)).fetchall()
            if (order['rule_version'],order['numeric_profile'])!=(RULE_VERSION,NUMERIC_PROFILE) or len(rows)!=len(calculated.lines):raise ValueError('规则/行数不一致')
            amounts=calculated.totals
            if (order['income_cents'],order['cost_cents'],order['profit_cents'])!=(amounts.income_cents,amounts.cost_cents,amounts.profit_cents):raise ValueError('订单金额不一致')
            for saved,line in zip(rows,calculated.lines):
                expected=(line.sequence,line.raw.line_kind,encoded(asdict(line.raw)),encoded(dict(line.normalized)),encoded(price_wire(line.price)) if line.price else None,line.amounts.income_cents,line.amounts.cost_cents,line.amounts.profit_cents,line.subtotal_before_cents)
                actual=tuple(saved[k] for k in ('sequence','kind','raw_json','normalized_json','price_json','income_cents','cost_cents','profit_cents','subtotal_before_cents'))
                if actual!=expected:raise ValueError('明细快照不一致')
            if order['state']=='active':totals=[a+b for a,b in zip(totals,(amounts.income_cents,amounts.cost_cents,amounts.profit_cents))]
        except (KeyError,TypeError,ValueError) as exc:raise InvalidDatabase('订单/明细/快照核对失败') from exc
    return {'ledger_id':meta['ledger_id'],'schema_version':schema.VERSION,'schema_hash':meta['schema_hash'],'revision':meta['revision'],'counts':counts,'active_income_cents':str(totals[0]),'active_cost_cents':str(totals[1]),'active_profit_cents':str(totals[2])}
