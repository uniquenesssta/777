"""Audit-delta aggregation and authenticated snapshot pagination."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quote_core import PriceSnapshot,PriceItem,QuoteSnapshot,NormalLine,DraftDetails
from quote_service.hosting import initialize,load
from quote_service.protocol import APIError
from quote_service.query import VERSION


def uid():return str(uuid.uuid4())


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        initialize(self.root/'host',self.root/'backup','manager','fixture-password-123',hosts=['localhost'],auxiliary=os.name!='nt')
        _,_,self.service=load(self.root/'host',auxiliary=os.name!='nt');a=self.service.auth
        identity=a.login('manager','fixture-password-123','fixture');self.admin=a.authenticate(identity['token'])
        for name in ('one','two'):a.create_account(self.admin,name,'fixture-password-123','sales')
        self.one=a.authenticate(a.login('one','fixture-password-123','fixture')['token']);self.two=a.authenticate(a.login('two','fixture-password-123','fixture')['token'])
        self.service.ledger.publish_prices(uid(),self.admin,PriceSnapshot('v1',(PriceItem('single','10','4','1',True),)))
        self.orders=[self.add(self.one,'客户甲'),self.add(self.one,'客户乙'),self.add(self.two,'客户甲')]
    def tearDown(self):self.temp.cleanup()
    def add(self,actor,customer):
        return self.service.ledger.submit_order(uid(),actor,QuoteSnapshot('v1',(NormalLine('single','2'),)),DraftDetails(customer,'000123','wechat'))
    def listing(self,actor=None,**query):return self.service.listing(actor or self.admin,{k:[str(v)] for k,v in query.items()})

    def test_first_scan_then_page_hits_do_not_rescan_full_ledger(self):
        value=self.listing(limit=1);self.assertEqual(value['total'],3);self.assertEqual(value['totals']['income_cents'],'6000')
        for _ in range(5):self.listing(offset=1,limit=1)
        self.assertEqual(self.service.queries.full_scans,1);self.assertEqual(self.service.queries.delta_rows,0)

    def test_submit_note_void_restore_are_exact_audit_deltas(self):
        self.listing();self.listing(self.one,q='客户甲');order=self.orders[0]
        self.service.ledger.append_note(uid(),self.one,order['order_id'],'new',expected_revision=1)
        self.assertEqual(self.listing()['totals']['income_cents'],'6000')
        self.service.ledger.set_state(uid(),self.admin,order['order_id'],'void','reason',expected_revision=2)
        self.assertEqual(self.listing()['totals']['income_cents'],'4000');self.assertEqual(self.listing(self.one,q='客户甲')['totals']['income_cents'],'0')
        self.service.ledger.set_state(uid(),self.admin,order['order_id'],'active','reason',expected_revision=3)
        self.assertEqual(self.listing()['totals']['income_cents'],'6000')
        self.add(self.two,'added');self.assertEqual(self.listing()['totals']['income_cents'],'8000')
        self.assertEqual(self.service.queries.full_scans,1);self.assertEqual(self.service.queries.delta_rows,4)

    def test_sales_scope_search_and_total_never_expose_other_owner_or_cost(self):
        value=self.listing(self.one,q='客户甲');self.assertEqual(value['total'],1);self.assertEqual(value['orders'][0]['order_id'],self.orders[0]['order_id'])
        self.assertEqual(value['totals'],{'income_cents':'2000'})
        for field in ('cost_cents','profit_cents','ledger_revision','owner_id'):self.assertNotIn('"'+field+'"',json.dumps(value))
        with self.assertRaises(APIError):self.listing(self.one,owner_id=self.two.subject)

    def test_signed_cursor_same_snapshot_returns_each_order_once(self):
        seen=[];cursor=None
        while True:
            value=self.listing(limit=1,**({'cursor':cursor} if cursor else {}));seen.extend(row['order_id'] for row in value['orders']);cursor=value['next_cursor']
            if not cursor:break
        self.assertEqual(len(seen),3);self.assertEqual(set(seen),{row['order_id'] for row in self.orders})

    def test_cursor_tamper_cross_actor_filter_or_limit_are_refused(self):
        value=self.listing(limit=1);cursor=value['next_cursor']
        for kwargs in [{'limit':1,'cursor':cursor[:-1]+'x'},{'limit':2,'cursor':cursor},{'limit':1,'cursor':cursor,'q':'客户甲'}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(APIError):self.listing(**kwargs)
        with self.assertRaises(APIError):self.listing(self.one,limit=1,cursor=cursor)

    def test_changed_view_and_restart_refuse_cursor_without_silent_page_drift(self):
        value=self.listing(limit=1);self.add(self.one,'changed')
        for query in [{'limit':1,'cursor':value['next_cursor']},{'limit':1,'offset':1,'view':value['view']}]:
            with self.assertRaises(APIError) as caught:self.listing(**query)
            self.assertEqual(caught.exception.code,'QUERY_VIEW_CHANGED')
        _,_,reopened=load(self.root/'host',auxiliary=os.name!='nt')
        with self.assertRaises(APIError):reopened.listing(self.admin,{'limit':['1'],'cursor':[value['next_cursor']]})

    def test_literal_unicode_and_sql_wildcard_queries_do_not_change_scope(self):
        self.add(self.one,'100%_中文 A')
        for q in ('100%_中文 a','000123','wechat'):
            self.assertGreater(self.listing(self.one,q=q)['total'],0)
        self.assertEqual(self.listing(self.one,q="%' OR 1=1 --")['total'],0)

    def test_bounds_duplicate_query_future_versions_and_cursor_offset_rejected(self):
        for query in [{'limit':201},{'offset':-1},{'format':'future-v2'},{'state':'all'},{'q':'a'*257}]:
            with self.subTest(query=query),self.assertRaises(APIError):self.listing(**query)
        with self.assertRaises(APIError):self.service.listing(self.admin,{'limit':['1','2']})
        cursor=self.listing(limit=1)['next_cursor']
        with self.assertRaises(APIError):self.listing(limit=1,offset=1,cursor=cursor)

    def test_summary_cache_is_bounded_and_rebuilds_without_financial_change(self):
        before=self.service.ledger.inventory()
        for i in range(40):self.listing(q='absent'+str(i))
        self.assertEqual(len(self.service.queries.summaries),32);self.assertEqual(self.listing()['total'],3);self.assertEqual(self.service.ledger.inventory(),before)

    def test_state_filter_total_counts_void_but_effective_totals_are_zero(self):
        order=self.orders[0];self.service.ledger.set_state(uid(),self.admin,order['order_id'],'void','reason',expected_revision=1)
        value=self.listing(state='void');self.assertEqual(value['total'],1);self.assertEqual(value['totals'],{'income_cents':'0','cost_cents':'0','profit_cents':'0'})
