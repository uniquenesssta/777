"""Single-process ASGI service. Uvicorn terminates TLS; no shared DB clients."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from urllib.parse import parse_qs

from quote_core import calculate_quote, parse_price_config
from quote_ledger import LedgerError, Conflict, Forbidden, InvalidDatabase, UnknownCommit
from quote_ledger.store import verify,digest
from .protocol import APIError, BODY_LIMIT, decode, fields, quote, details, prices, financial, catalog, calculated, text


class Service:
    def __init__(self, ledger, auth, backups=None):
        self.ledger, self.auth, self.backups = ledger, auth, backups
        from .query import Queries
        self.queries = Queries(); self.outputs = None

    def backup(self,**kwargs):
        try:
            from .recovery import bundle
            with self.auth._lock:
                result=self.backups.create_backup(self.ledger,**kwargs)
                result=bundle(self,result,self.host_root,auxiliary=self.auxiliary)
            self.auth.record_backup_health(success=result)
            return result
        except Exception as exc:
            self.auth.record_backup_health(error='BACKUP_FAILED:'+type(exc).__name__)
            raise

    def scheduled_backup(self,plan):
        try:
            from .recovery import bundle,retain
            with self.auth._lock:
                result=self.backups.run_due(self.ledger,now=datetime.now(timezone(timedelta(minutes=plan['offset_minutes']))),
                                           interval_minutes=plan['interval_minutes'],daily_hour=plan['daily_hour'])
                if result:
                    result=bundle(self,result,self.host_root,auxiliary=self.auxiliary)
                    self.auth.record_backup_health(success=result)
                    self.backups.retain(rolling=plan['rolling'],daily=plan['daily']);retain(self)
            return result
        except Exception as exc:
            self.auth.record_backup_health(error='BACKUP_OR_RETENTION_FAILED:'+type(exc).__name__)
            raise

    def active_prices(self):
        if getattr(self.ledger,'backend',None)=='rust':return self.ledger.active_prices()
        with self.ledger.connection(readonly=True) as c:
            identifier=verify(c)['active_price_id']
            if identifier is None:raise APIError(409,'PRICES_NOT_PUBLISHED')
            row=c.execute('SELECT payload_json,payload_sha256 FROM price_versions WHERE price_id=?',(identifier,)).fetchone()
            if row is None or digest(row['payload_json'])!=row['payload_sha256']:raise APIError(503,'LEDGER_UNAVAILABLE')
            result=parse_price_config(row['payload_json'],price_version_id=identifier)
            if result.status!='ok':raise APIError(503,'LEDGER_UNAVAILABLE')
            return result.config.prices

    def order(self, actor, identifier):
        with self.ledger.connection(readonly=True) as c:
            c.execute('BEGIN')
            try:row=self.ledger._owned_order(c,actor,identifier)
            except (Forbidden,LedgerError):raise APIError(404,'NOT_FOUND') from None
            value={'order_id':row['order_id'],'revision':row['revision'],'state':row['state'],
                   'price_version_id':row['price_id'],'created_at':row['created_at'],
                   'rule_version':row['rule_version'],'numeric_profile':row['numeric_profile'],
                   'details':json.loads(row['details_json']),**financial({k:str(row[k]) for k in ('income_cents','cost_cents','profit_cents')},actor)}
            if actor.role=='admin':value['owner_id']=row['owner_id']
            lines=[]
            for line in c.execute('SELECT * FROM lines WHERE order_id=? ORDER BY sequence',(identifier,)):
                normal=json.loads(line['normalized_json'])
                if actor.role!='admin':normal={k:v for k,v in normal.items() if k in {'q','h','w','sale','k','percent','single'}}
                lines.append({'sequence':line['sequence'],'raw':json.loads(line['raw_json']),'normalized':normal,
                              'subtotal_before_cents':str(line['subtotal_before_cents']),
                              **financial({k:str(line[k]) for k in ('income_cents','cost_cents','profit_cents')},actor)})
            value['lines']=lines
            value['notes']=[{'note_id':n['note_id'],'author':n['author_id'],'body':n['body'],'created_at':n['created_at']}
                            for n in c.execute('SELECT * FROM notes WHERE order_id=? ORDER BY created_at,note_id',(identifier,))]
            return value

    def listing(self, actor, params):
        return self.queries.listing(self.ledger, actor, params)

    def output_task(self, actor, data):
        from .output_render import FORMAT, KINDS, payload_hash
        from quote_ledger.store import identifier
        fields(data, {'request_id', 'order_id', 'expected_revision', 'kind'}, {'format'})
        data = {**data, 'format': data.get('format', FORMAT)}
        if data['format'] != FORMAT: raise APIError(409, 'OUTPUT_VERSION_CONFLICT')
        identifier(data['request_id']); identifier(data['order_id'])
        if type(data['kind']) is not str or data['kind'] not in KINDS or type(data['expected_revision']) is not int or data['expected_revision'] < 1: raise APIError(422, 'INVALID_OUTPUT_REQUEST')
        if data['kind'] == 'excel_admin': self.auth.admin(actor)
        if self.outputs is None: raise APIError(503, 'OUTPUTS_NOT_INITIALIZED')
        previous = self.outputs.receipt(actor, data['request_id'], payload_hash({'actor': actor.subject, 'role': actor.role, **data}))
        if previous is not None: return previous
        order = self.order(actor, data['order_id'])
        if order['revision'] != data['expected_revision']: raise APIError(409, 'ORDER_REVISION_CHANGED')
        return self.outputs.enqueue(actor, data, order)

    def handle(self, method, path, token='', data=None, query='', peer='local'):
        if getattr(self,'host_backend','python')!='python':raise APIError(409,'RUST_HOST_SELECTED')
        # Account revocations and authorizations are serialized with dispatch;
        # one service process owns this ledger (also enforced by host file lock).
        with self.auth._lock:
            if method=='POST' and path=='/v1/login':
                fields(data,{'username','password'})
                return self.auth.login(data['username'],data['password'],peer)
            actor=self.auth.authenticate(token)
            if method == 'POST' and type(data) is dict and 'request_id' in data:
                from quote_ledger.store import identifier
                identifier(data['request_id'])
                if path == '/v1/outputs' or path.startswith('/v1/outputs/'):
                    with self.ledger.connection(readonly=True) as c:
                        if c.execute('SELECT 1 FROM requests WHERE request_id=?', (data['request_id'],)).fetchone(): raise Conflict('Financial request ID already used')
                elif self.outputs and self.outputs.has_request(data['request_id']): raise Conflict('Output request ID already used')
            if method == 'GET' and path == '/v1/capabilities':
                from quote_core.numbers import RULE_VERSION, NUMERIC_PROFILE
                return {'protocol': '777-service-v1', 'output_format': '777-output-v1', 'query_format': '777-query-v1', 'rule_version': RULE_VERSION, 'numeric_profile': NUMERIC_PROFILE, 'cents_encoding': 'decimal-string'}
            if path == '/v1/outputs' and method == 'POST': return self.output_task(actor, data)
            if path == '/v1/outputs' and method == 'GET':
                if self.outputs is None: raise APIError(503, 'OUTPUTS_NOT_INITIALIZED')
                return self.outputs.listing(actor)
            if path.startswith('/v1/outputs/'):
                if self.outputs is None: raise APIError(503, 'OUTPUTS_NOT_INITIALIZED')
                parts = path.removeprefix('/v1/outputs/').split('/')
                if len(parts) == 1 and method == 'GET': return self.outputs.status(actor, parts[0])
                if len(parts) == 2 and parts[1] == 'content' and method == 'GET': return self.outputs.content(actor, parts[0])
                if len(parts) == 2 and parts[1] == 'retry' and method == 'POST':
                    fields(data, {'request_id'}); return self.outputs.retry(actor, parts[0], data['request_id'])
                raise APIError(404, 'NOT_FOUND')
            if method=='POST' and path=='/v1/logout':
                fields(data,set());self.auth.logout(token);return {'logged_out':True}
            if method=='GET' and path=='/v1/me':return {'subject':actor.subject,'role':actor.role,'protocol':'777-service-v1'}
            if method=='GET' and path=='/v1/prices':return catalog(self.active_prices(),actor)
            if method=='POST' and path=='/v1/prices':
                self.auth.admin(actor);fields(data,{'request_id','prices','expected_price_version_id'})
                return self.ledger.publish_prices(data['request_id'],actor,prices(data['prices']),expected_price_version_id=data['expected_price_version_id'])
            if method=='POST' and path=='/v1/calculate':
                fields(data,{'snapshot'});snapshot=quote(data['snapshot'])
                if getattr(self.ledger,'backend',None)=='rust':
                    try:return calculated(self.ledger.calculate(snapshot),actor)
                    except Conflict:raise APIError(409,'PRICE_VERSION_CHANGED') from None
                current=self.active_prices()
                if snapshot.price_version_id!=current.price_version_id:raise APIError(409,'PRICE_VERSION_CHANGED')
                return calculated(calculate_quote(snapshot,current),actor)
            if method=='POST' and path=='/v1/orders':
                fields(data,{'request_id','snapshot','details'})
                return financial(self.ledger.submit_order(data['request_id'],actor,quote(data['snapshot']),details(data['details'])),actor)
            if method=='GET' and path=='/v1/orders':return self.listing(actor,parse_qs(query,keep_blank_values=True))
            if method=='GET' and path.startswith('/v1/orders/'):return self.order(actor,path.removeprefix('/v1/orders/'))
            if method=='POST' and path=='/v1/notes':
                fields(data,{'request_id','order_id','body','expected_revision'})
                return financial(self.ledger.append_note(data['request_id'],actor,data['order_id'],data['body'],expected_revision=data['expected_revision']),actor)
            if method=='POST' and path=='/v1/state':
                self.auth.admin(actor);fields(data,{'request_id','order_id','state','reason','expected_revision'})
                return financial(self.ledger.set_state(data['request_id'],actor,data['order_id'],data['state'],data['reason'],expected_revision=data['expected_revision']),actor)
            if method=='GET' and path.startswith('/v1/requests/'):
                try:
                    key = path.removeprefix('/v1/requests/')
                    result = self.ledger.query_request(key, actor)
                    if result is None and self.outputs: result = self.outputs.receipt(actor, key)
                    return {'result':financial(result,actor) if result else None}
                except Forbidden:raise APIError(404,'NOT_FOUND') from None
            if method=='GET' and path=='/v1/settings':return self.auth.preferences()
            if method=='POST' and path=='/v1/settings':
                self.auth.admin(actor);fields(data,{'revision','export_dir','image_dir'})
                return self.auth.save_preferences(actor,**data)
            if method=='GET' and path=='/v1/accounts':return {'accounts':self.auth.accounts(actor)}
            if method=='POST' and path=='/v1/accounts':
                self.auth.admin(actor);fields(data,{'username','password','role'})
                return self.auth.create_account(actor,data['username'],data['password'],data['role'])
            if method=='POST' and path.startswith('/v1/accounts/'):
                self.auth.admin(actor);fields(data,set(),{'password','role','enabled'})
                if not data:raise APIError(422,'INVALID_FIELDS')
                return self.auth.update_account(actor,path.removeprefix('/v1/accounts/'),secret=data.get('password'),role=data.get('role'),enabled=data.get('enabled'))
            if path=='/v1/backup':
                self.auth.admin(actor)
                if self.backups is None:raise APIError(503,'BACKUP_NOT_CONFIGURED')
                if method=='GET':
                    health=self.auth.backup_health()
                    try:status=self.backups.status()
                    except Exception:status={'status':'unavailable','last_success':health['last_success']}
                    return {'target':str(self.backups.root),'plan':self.auth.backup_plan(),**status,'service_health':health}
                if method=='POST':
                    fields(data,{'kind'});return self.backup(kind=data['kind'])
            if method=='POST' and path=='/v1/backup-plan':
                self.auth.admin(actor);fields(data,{'revision','interval_minutes','daily_hour','rolling','daily','offset_minutes'})
                return self.auth.save_backup_plan(actor,data)
            raise APIError(404,'NOT_FOUND')


class Application:
    def __init__(self, service):
        self.service=service
        self._capacity=None

    async def __call__(self, scope, receive, send):
        if scope['type']=='lifespan':
            scheduler=None; output_worker=None; self._outputs_stop=False
            while True:
                message=await receive()
                if message['type']=='lifespan.startup':
                    self._capacity=asyncio.Semaphore(8)
                    if self.service.backups:scheduler=asyncio.create_task(self._schedule())
                    if self.service.outputs:
                        await asyncio.to_thread(self.service.outputs.recover)
                        output_worker=asyncio.create_task(self._output_schedule())
                    await send({'type':'lifespan.startup.complete'})
                elif message['type']=='lifespan.shutdown':
                    self._outputs_stop=True
                    if output_worker:
                        await output_worker  # Finish the real write before releasing host ownership.
                    if scheduler:
                        scheduler.cancel()
                        try:await scheduler
                        except asyncio.CancelledError:pass
                    await send({'type':'lifespan.shutdown.complete'});return
        if scope['type']!='http':return
        status=200
        try:
            if scope.get('scheme')!='https':raise APIError(400,'HTTPS_REQUIRED')
            headers={}
            for key,value in scope.get('headers',[]):
                key=key.lower()
                if key in headers and key in {b'authorization',b'content-type',b'content-length'}:raise APIError(400,'DUPLICATE_HEADERS')
                headers[key]=value
            if b'origin' in headers:raise APIError(403,'BROWSER_ORIGIN_NOT_ALLOWED')
            authorization=headers.get(b'authorization',b'')
            if len(authorization)>256:raise APIError(401,'UNAUTHENTICATED')
            try:token=authorization.removeprefix(b'Bearer ').decode('ascii') if authorization.startswith(b'Bearer ') else ''
            except UnicodeError:raise APIError(401,'UNAUTHENTICATED') from None
            method=scope['method'];raw=bytearray()
            if method=='POST':
                if headers.get(b'content-type',b'').split(b';')[0].strip()!=b'application/json':raise APIError(415,'JSON_REQUIRED')
                while True:
                    event=await asyncio.wait_for(receive(),10)
                    if event['type']=='http.disconnect':return
                    raw.extend(event.get('body',b''))
                    if len(raw)>BODY_LIMIT:raise APIError(413,'BODY_TOO_LARGE')
                    if not event.get('more_body'):break
            data=decode(raw) if method=='POST' else None
            if self._capacity is None:self._capacity=asyncio.Semaphore(8)
            async with self._capacity:
                result=await asyncio.to_thread(self.service.handle,method,scope['path'],token,data,
                                              scope.get('query_string',b'').decode('ascii'),scope.get('client',('unknown',))[0])
        except APIError as exc:status=exc.status;result={'error':exc.code}
        except UnknownCommit as exc:status=202;result={'error':'COMMIT_UNKNOWN','request_id':exc.request_id}
        except Forbidden:status=403;result={'error':'FORBIDDEN'}
        except Conflict:status=409;result={'error':'REVISION_OR_PRICE_CONFLICT'}
        except InvalidDatabase:status=503;result={'error':'LEDGER_UNAVAILABLE'}
        except sqlite3.OperationalError:status=503;result={'error':'STORE_BUSY_OR_UNAVAILABLE'}
        except (LedgerError,ValueError,TypeError,sqlite3.IntegrityError):status=422;result={'error':'INVALID_BUSINESS_INPUT'}
        except Exception:status=500;result={'error':'SERVICE_FAILED'}
        body=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        await send({'type':'http.response.start','status':status,'headers':[(b'content-type',b'application/json; charset=utf-8'),(b'cache-control',b'no-store'),(b'content-length',str(len(body)).encode())]})
        await send({'type':'http.response.body','body':body})

    async def _schedule(self):
        while True:
            await asyncio.sleep(15)
            try:
                plan=await asyncio.to_thread(self.service.auth.backup_plan)
                await asyncio.to_thread(self.service.scheduled_backup,plan)
            except Exception:
                # Failure details remain in the private backup index; no
                # credentials or customer data are printed by the scheduler.
                pass

    async def _output_schedule(self):
        while not self._outputs_stop:
            try: worked = await asyncio.to_thread(self.service.outputs.run_one, self.service)
            except Exception: worked = False
            if not worked and not self._outputs_stop: await asyncio.sleep(0.5)
