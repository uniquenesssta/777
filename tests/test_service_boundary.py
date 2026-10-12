"""Authentication/authorization/DTO/replay tests through real HTTPS and SQLite."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Barrier,Thread
import unittest
from unittest.mock import patch
import uuid

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from quote_core import QuoteSnapshot,NormalLine,DiscountLine,DraftDetails,PriceSnapshot,PriceItem
from quote_service.auth import Auth
from quote_service.app import Application
from quote_service.client import Client,CommitUnknown,connection_settings
from quote_service.protocol import APIError,decode
from quote_service.journal import MemoryJournal
from service_fixture import Hosted


def uid():return str(uuid.uuid4())
def snapshot():return QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),DiscountLine('90%')))
def body(request=None):return {'request_id':request or uid(),'snapshot':asdict(snapshot()),'details':asdict(DraftDetails('客户','000123','微信'))}
def no_finances(case,value):
    if isinstance(value,dict):
        case.assertFalse(set(value)&{'cost','profit','cost_cents','profit_cents','price_json','ledger_revision','owner_id'})
        for v in value.values():no_finances(case,v)
    elif isinstance(value,list):
        for v in value:no_finances(case,v)


class ServiceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.host=Hosted()
    @classmethod
    def tearDownClass(cls):cls.host.close()
    def setUp(self):
        self.admin=self.host.client('manager');self.sales=self.host.client('sales-one');self.other=self.host.client('sales-two')

    def test_anonymous_invalid_token_and_client_claimed_role_cannot_authorize(self):
        client=Client(self.sales.settings)
        for token in ('','admin','A'*43):
            client.token=token
            with self.subTest(token=token),self.assertRaises(APIError) as caught:client.request('GET','/v1/orders')
            self.assertEqual(caught.exception.status,401)
        with self.assertRaises(APIError):self.sales.request('POST','/v1/orders',{**body(),'role':'admin'})

    def test_sales_catalog_calculation_order_receipt_and_list_never_contain_finances(self):
        for result in (self.sales.request('GET','/v1/prices'),self.sales.request('POST','/v1/calculate',{'snapshot':asdict(snapshot())})):
            no_finances(self,result)
        data=body();receipt=self.sales.request('POST','/v1/orders',data)
        self.assertEqual(receipt['income_cents'],'3600');no_finances(self,receipt)
        for result in (self.sales.request('GET','/v1/orders/'+receipt['order_id']),self.sales.request('GET','/v1/orders'),self.sales.request('GET','/v1/requests/'+data['request_id'])):no_finances(self,result)
        admin=self.admin.request('GET','/v1/orders/'+receipt['order_id']);self.assertEqual((admin['cost_cents'],admin['profit_cents']),('1600','2000'))

    def test_cross_owner_orders_notes_receipts_and_state_are_denied(self):
        data=body();order=self.sales.request('POST','/v1/orders',data)
        for method,path,payload in [('GET','/v1/orders/'+order['order_id'],None),('GET','/v1/requests/'+data['request_id'],None),('POST','/v1/notes',{'request_id':uid(),'order_id':order['order_id'],'body':'越权','expected_revision':1})]:
            with self.subTest(path=path),self.assertRaises(APIError):self.other.request(method,path,payload)
        with self.assertRaises(APIError) as caught:self.sales.request('POST','/v1/state',{'request_id':uid(),'order_id':order['order_id'],'state':'void','reason':'越权','expected_revision':1})
        self.assertEqual(caught.exception.status,403)

    def test_sales_cannot_publish_prices_settings_accounts_plan_or_read_backups(self):
        paths=['/v1/prices','/v1/settings','/v1/accounts','/v1/backup-plan','/v1/backup']
        for path in paths:
            with self.subTest(path=path),self.assertRaises(APIError) as caught:self.sales.request('POST',path,{'role':'admin'})
            self.assertEqual(caught.exception.status,403)
        for path in ['/v1/accounts','/v1/backup']:
            with self.subTest(path=path),self.assertRaises(APIError):self.sales.request('GET',path)

    def test_client_financial_totals_prices_and_actor_fields_are_rejected(self):
        before=self.host.service.ledger.inventory()
        for field in ('income_cents','cost_cents','actor','owner_id','prices'):
            with self.subTest(field=field),self.assertRaises(APIError):self.sales.request('POST','/v1/orders',{**body(),field:'forged'})
        self.assertEqual(self.host.service.ledger.inventory(),before)

    def test_duplicate_request_conflict_and_stale_price_gate_are_service_enforced(self):
        data=body();order=self.sales.request('POST','/v1/orders',data)
        self.assertEqual(self.sales.request('POST','/v1/orders',data),order)
        changed=json.loads(json.dumps(data));changed['snapshot']['lines'][0]['q']='5'
        with self.assertRaises(APIError) as caught:self.sales.request('POST','/v1/orders',changed)
        self.assertEqual(caught.exception.status,409)
        stale=body();stale['snapshot']['price_version_id']='not-published'
        with self.assertRaises(APIError):self.sales.request('POST','/v1/orders',stale)

    def test_lost_reply_persists_original_then_queries_without_duplicate_or_repricing(self):
        journal=MemoryJournal();original=self.sales.request
        def lost(method,path,data=None):
            result=original(method,path,data)
            if method=='POST' and path=='/v1/orders':raise OSError('lost after response')
            return result
        before=self.host.service.ledger.inventory()['counts']['orders']
        with patch.object(self.sales,'request',side_effect=lost),self.assertRaises(CommitUnknown):self.sales.submit(snapshot(),DraftDetails(),journal)
        saved=journal.read();self.assertIsNotNone(saved)
        with self.assertRaises(APIError):self.sales.submit(snapshot(),DraftDetails(),journal)
        recovered=self.sales.check_pending(journal);self.assertIsNotNone(recovered['result']);self.assertIsNone(journal.read())
        self.assertEqual(self.host.service.ledger.inventory()['counts']['orders'],before+1)

    def test_unsubmitted_pending_retries_same_id_and_other_identity_cannot_replay(self):
        journal=MemoryJournal()
        with patch.object(self.sales,'request',side_effect=OSError('before send')),self.assertRaises(CommitUnknown):self.sales.submit(snapshot(),DraftDetails(),journal)
        request=journal.read()['body']['request_id']
        with self.assertRaises(APIError):self.other.check_pending(journal,retry=True)
        self.assertEqual(self.sales.check_pending(journal)['request_id'],request)
        result=self.sales.check_pending(journal,retry=True)['result'];self.assertEqual(result['request_id'],request);self.assertIsNone(journal.read())

    def test_two_actual_https_clients_same_request_create_one_order(self):
        data=body();client2=self.host.client();barrier=Barrier(3);results=[];errors=[]
        def send(client):
            try:barrier.wait();results.append(client.request('POST','/v1/orders',data))
            except Exception as exc:errors.append(exc)
        before=self.host.service.ledger.inventory()['counts']['orders']
        threads=[Thread(target=send,args=(client,)) for client in (self.sales,client2)]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join(10);self.assertFalse(t.is_alive())
        self.assertEqual(errors,[]);self.assertEqual(len(results),2);self.assertEqual(results[0],results[1])
        self.assertEqual(self.host.service.ledger.inventory()['counts']['orders'],before+1)

    def test_owner_note_revision_and_admin_void_restore_keep_original_financial_history(self):
        order=self.sales.request('POST','/v1/orders',body());payload={'request_id':uid(),'order_id':order['order_id'],'body':'追加','expected_revision':1}
        note=self.sales.request('POST','/v1/notes',payload);self.assertEqual(note['revision'],2)
        self.assertEqual(self.sales.request('POST','/v1/notes',payload),note)
        with self.assertRaises(APIError):self.sales.request('POST','/v1/notes',{**payload,'request_id':uid()})
        for state,revision in [('void',2),('active',3)]:self.admin.request('POST','/v1/state',{'request_id':uid(),'order_id':order['order_id'],'state':state,'reason':'管理员原因','expected_revision':revision})
        saved=self.admin.request('GET','/v1/orders/'+order['order_id']);self.assertEqual(saved['revision'],4);self.assertEqual(len(saved['notes']),1);self.assertEqual(saved['cost_cents'],'1600')

    def test_manager_directory_cas_and_sales_inherited_values_are_same(self):
        previous=self.admin.request('GET','/v1/settings')
        paths=('\\\\fixture-host\\reports','\\\\fixture-host\\images') if os.name=='nt' else (str(self.host.root/'reports'),str(self.host.root/'images'))
        payload={'revision':previous['revision'],'export_dir':paths[0],'image_dir':paths[1]}
        value=self.admin.request('POST','/v1/settings',payload);self.assertEqual(value,self.sales.request('GET','/v1/settings'))
        with self.assertRaises(APIError) as caught:self.admin.request('POST','/v1/settings',payload)
        self.assertEqual(caught.exception.status,409)

    def test_logout_revocation_role_change_and_restart_authentication(self):
        user='case-'+uid();created=self.admin.request('POST','/v1/accounts',{'username':user,'password':self.host.password,'role':'sales'})
        client=self.host.client(user);token=client.token
        reopened=Auth(self.host.service.auth.path);self.assertEqual(reopened.authenticate(token).subject,created['id'])
        self.admin.request('POST','/v1/accounts/'+created['id'],{'enabled':False})
        with self.assertRaises(APIError):client.request('GET','/v1/me')
        with self.assertRaises(APIError):reopened.authenticate(token)
        self.sales.logout()
        with self.assertRaises(APIError):self.sales.request('GET','/v1/me')

    def test_backup_plan_is_persisted_cas_and_admin_only(self):
        status=self.admin.request('GET','/v1/backup');plan=status['plan']
        changed={**plan,'interval_minutes':45};new=self.admin.request('POST','/v1/backup-plan',changed)
        self.assertEqual(new['interval_minutes'],45);self.assertEqual(Auth(self.host.service.auth.path).backup_plan(),new)
        with self.assertRaises(APIError):self.admin.request('POST','/v1/backup-plan',changed)
        with self.assertRaises(APIError):self.sales.request('POST','/v1/backup-plan',new)

    def test_certificate_replacement_and_cleartext_urls_are_refused_before_credentials(self):
        with self.assertRaises(APIError):connection_settings({**self.sales.settings,'url':'http://127.0.0.1'})
        client=Client({**self.sales.settings,'certificate_sha256':'0'*64})
        with self.assertRaises(APIError) as caught:client.login('manager',self.host.password)
        self.assertEqual(caught.exception.code,'CERTIFICATE_PIN_MISMATCH')

    def test_actual_tls_hostname_verification_rejects_wrong_server_name(self):
        import ssl,socket
        context=ssl.create_default_context(cafile=self.sales.settings['certificate'])
        raw=socket.create_connection(('127.0.0.1',self.host.port),timeout=5)
        try:
            with self.assertRaises(ssl.SSLCertVerificationError):context.wrap_socket(raw,server_hostname='not-this-host.example')
        finally:raw.close()
        self.assertIn(self.sales.last_tls_version,('TLSv1.2','TLSv1.3'))

    def test_backup_failure_is_persisted_locally_and_does_not_undo_order(self):
        order=self.sales.request('POST','/v1/orders',body());original=self.host.service.ledger.inventory()
        verified=self.admin.request('POST','/v1/backup',{'kind':'maintenance'})
        with patch.object(self.host.service.backups,'create_backup',side_effect=OSError('simulated backup target unavailable')):
            with self.assertRaises(APIError):self.admin.request('POST','/v1/backup',{'kind':'maintenance'})
        status=self.admin.request('GET','/v1/backup');self.assertEqual(status['service_health']['last_success'],verified)
        self.assertIn('BACKUP_FAILED',status['service_health']['error'])
        self.assertEqual(Auth(self.host.service.auth.path).backup_health(),status['service_health'])
        self.assertEqual(self.host.service.ledger.inventory(),original)
        self.assertEqual(self.sales.request('GET','/v1/orders/'+order['order_id'])['income_cents'],'3600')

    def test_malformed_duplicate_nonfinite_and_oversized_json_are_rejected(self):
        for raw in (b'{"role":"sales","role":"admin"}',b'{"x":NaN}',b'[]'*1000000,b'\xff'):
            with self.subTest(size=len(raw)),self.assertRaises(APIError):decode(raw)

    def test_authenticated_pagination_is_bounded_and_sales_scope_totals_are_exact(self):
        own=self.sales.request('GET','/v1/orders?offset=0&limit=2');self.assertLessEqual(len(own['orders']),2)
        no_finances(self,own)
        with self.assertRaises(APIError):self.sales.request('GET','/v1/orders?limit=100000')
        with self.assertRaises(APIError):self.sales.request('GET','/v1/orders?owner_id='+self.other.subject)


class AuthPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'auth.sqlite3'
        self.auth=Auth.create(self.path,'manager','fixture-password-123');identity=self.auth.login('manager','fixture-password-123','fixture')
        self.actor=self.auth.authenticate(identity['token']);self.token=identity['token']
    def tearDown(self):self.temp.cleanup()

    def test_passwords_and_raw_tokens_are_not_stored_and_sessions_expire(self):
        raw=self.path.read_bytes();self.assertNotIn(b'fixture-password-123',raw);self.assertNotIn(self.token.encode(),raw)
        self.auth.clock=lambda:10**12
        with self.assertRaises(APIError):self.auth.authenticate(self.token)

    def test_password_reset_revokes_all_sessions_and_old_password(self):
        user=self.auth.create_account(self.actor,'sales-new','fixture-password-123','sales')
        old=self.auth.login('sales-new','fixture-password-123','fixture')['token']
        self.auth.update_account(self.actor,user['id'],secret='changed-password-456')
        with self.assertRaises(APIError):self.auth.authenticate(old)
        with self.assertRaises(APIError):self.auth.login('sales-new','fixture-password-123','fixture')
        self.assertEqual(self.auth.login('sales-new','changed-password-456','fixture')['subject'],user['id'])

    def test_unknown_login_is_generic_and_attempts_are_limited(self):
        for i in range(5):
            with self.assertRaises(APIError) as caught:self.auth.login('unknown','bad','peer')
            self.assertEqual(caught.exception.code,'UNAUTHENTICATED')
        with self.assertRaises(APIError) as caught:self.auth.login('unknown','bad','peer')
        self.assertEqual(caught.exception.status,429)

    def test_last_admin_cannot_be_removed_or_demoted(self):
        for changes in ({'enabled':False},{'role':'sales'}):
            with self.subTest(changes=changes),self.assertRaises(APIError):self.auth.update_account(self.actor,self.actor.subject,**changes)
        self.assertEqual(self.auth.authenticate(self.token).role,'admin')

    def test_unknown_auth_schema_is_refused_without_overwrite(self):
        with self.auth.connection() as c:c.execute('PRAGMA user_version=999')
        before=self.path.read_bytes()
        with self.assertRaises(APIError):Auth(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_unexpected_auth_trigger_is_refused_without_rebuilding_database(self):
        with self.auth.connection() as c:c.execute('CREATE TRIGGER unexpected AFTER INSERT ON sessions BEGIN SELECT 1; END')
        before=self.path.read_bytes()
        with self.assertRaises(APIError):Auth(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_repeated_unknown_names_share_peer_rate_limit(self):
        for i in range(20):
            with self.assertRaises(APIError) as caught:self.auth.login('unknown-'+str(i),'invalid','rotating-peer')
            self.assertEqual(caught.exception.status,401)
        with self.assertRaises(APIError) as caught:self.auth.login('one-more-name','invalid','rotating-peer')
        self.assertEqual(caught.exception.status,429)


class ASGIGateTests(unittest.TestCase):
    def test_cleartext_duplicate_authorization_and_browser_origin_are_rejected(self):
        class Never:
            def handle(self,*args):raise AssertionError('business reached')
        app=Application(Never())
        async def invoke(scheme,headers):
            sent=[]
            async def receive():return {'type':'http.request','body':b'{}'}
            async def send(value):sent.append(value)
            await app({'type':'http','scheme':scheme,'method':'POST','path':'/v1/orders','headers':headers},receive,send)
            return sent[0]['status']
        for scheme,headers,expected in [('http',[],400),('https',[(b'authorization',b'one'),(b'authorization',b'two')],400),('https',[(b'origin',b'https://evil')],403)]:
            self.assertEqual(asyncio.run(invoke(scheme,headers)),expected)


if __name__=='__main__':unittest.main()
