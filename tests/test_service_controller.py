"""Headless owner-thread service controller checks, not native Tk acceptance."""
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import sys

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from quote_app.service_client import ServiceApplicationMixin
from quote_app.background import Value
from quote_service.journal import MemoryJournal
from quote_service.protocol import APIError
from quote_core import QuoteSnapshot,NormalLine,DraftDetails
from service_fixture import Hosted


class Root:
    def __init__(self):self.calls={};self.sequence=0;self.destroyed=False
    def after(self,delay,callback):self.sequence+=1;self.calls[self.sequence]=callback;return self.sequence
    def after_cancel(self,value):self.calls.pop(value,None)
    def destroy(self):self.destroyed=True


class Tree:
    def __init__(self):self.items={};self.selected=()
    def get_children(self):return tuple(self.items)
    def delete(self,*items):
        for item in items:self.items.pop(item,None)
    def selection(self):return self.selected
    def selection_set(self,item):self.selected=(item,)
    def insert(self,parent,index,iid,values):self.items[iid]=values


class Text:
    def __init__(self):self.text=''
    def configure(self,**kwargs):pass
    def delete(self,*args):self.text=''
    def insert(self,index,value):self.text=value


class Controller(ServiceApplicationMixin):
    def __init__(self,host,role='sales'):
        self.root=Root();self.quote_role=role;self.service_settings_file=str(host.root/(role+'-client.json'));self._svc_journal=MemoryJournal()
        self.setting_rows=[];self.calc_rows=[];self.default_items=[];self.feedback=[]
        self.user_name=Value('客户');self.order_no=Value('0001');self.wechat_no=Value('微信');self.export_dir_var=Value('')
        self.total_val=Value('');self.summary_income=Value('');self.quote_status_var=Value('')
        self.service_order_tree=Tree();self.service_detail_text=Text();self.service_detail_var=Value('')
        self._svc_offset=0
        self.initialize_background_io();self.initialize_quote_state()
        self._svc_client=host.client('manager' if role=='manager' else 'sales-one');self._storage_valid=True
        self._svc_prices=self._svc_client.request('GET','/v1/prices');self._svc_preferences=self._svc_client.request('GET','/v1/settings')
    def _new_text_var(self,value):return Value(value)
    def set_feedback(self,value,is_error=False):self.feedback.append((value,is_error))
    def clear_quote_display(self):self.total_val.set('—')
    def render_issues(self,issues):self.issues=issues
    def close(self):
        self.on_close()
        deadline=time.monotonic()+12
        while not self.root.destroyed and time.monotonic()<deadline:self._service_poll();time.sleep(.01)
        if not self.root.destroyed:raise RuntimeError('controller has not closed')
        if not self._svc_jobs.wait_closed(12):raise RuntimeError('controller worker still running')


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.host=Hosted()
    @classmethod
    def tearDownClass(cls):cls.host.close()
    def setUp(self):self.app=Controller(self.host)
    def tearDown(self):self.app.close()
    def wait(self,predicate):
        deadline=time.monotonic()+12
        while not predicate() and time.monotonic()<deadline:self.app._service_poll();time.sleep(.01)
        self.assertTrue(predicate(),self.app.feedback)

    def test_network_action_runs_off_owner_and_callback_on_owner(self):
        owner=threading.get_ident();seen=[]
        def action():seen.append(('worker',threading.get_ident()));return self.app._svc_client.request('GET','/v1/me')
        self.app._service_submit('identity',action,lambda result:seen.append(('callback',threading.get_ident())))
        self.wait(lambda:len(seen)==2);self.assertNotEqual(seen[0][1],owner);self.assertEqual(seen[1][1],owner)

    def test_stale_calculation_cannot_overwrite_new_input(self):
        from threading import Event
        started,release=Event(),Event();seen=[]
        def action():started.set();release.wait(3);return 'old-result'
        self.app._service_submit('calculate',action,seen.append,fresh=True);self.assertTrue(started.wait(3))
        self.app.quote_input_changed();release.set();self.wait(lambda:not self.app._svc_jobs.tasks)
        self.assertEqual(seen,[])

    def test_controller_never_reads_legacy_config_or_ledger_and_sales_state_is_blocked(self):
        with self.assertRaises(APIError):self.app._read_price_candidate()
        with self.assertRaises(APIError):self.app.get_report_excel_paths()
        with self.assertRaises(APIError):self.app._write_quote_excel(None)
        with self.assertRaises(APIError):self.app.delete_excel_path('legacy.xlsx')
        self.assertFalse(self.app.delete_current_excel_row());self.assertFalse(self.app.restore_current_excel_order())
        self.assertEqual(self.app.default_items,[])

    def test_pending_reply_loss_survives_window_close_and_is_queryable(self):
        client=self.app._svc_client;original=client.request
        def lost(method,path,data=None):
            value=original(method,path,data)
            if path=='/v1/orders':raise OSError('reply lost')
            return value
        with patch.object(client,'request',side_effect=lost):
            self.app._mutate('/v1/orders',{'snapshot':asdict(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),))),'details':asdict(DraftDetails())})
            self.app.on_close();self.wait(lambda:self.app.root.destroyed)
        journal=self.app._svc_journal;self.assertIsNotNone(journal.read())
        self.assertIsNotNone(client.check_pending(journal)['result']);self.assertIsNone(journal.read())
        # The normal teardown should not cancel an already destroyed root.
        self.app.on_close=lambda:None

    def test_sales_directory_observation_updates_inherited_values_without_local_apply(self):
        before=dict(self.app._svc_preferences)
        owner=self.host.client('manager')
        import os
        roots=('\\\\fixture-host\\new-reports','\\\\fixture-host\\new-images') if os.name=='nt' else (str(self.host.root/'new-reports'),str(self.host.root/'new-images'))
        owner.request('POST','/v1/settings',{'revision':before['revision'],'export_dir':roots[0],'image_dir':roots[1]})
        self.app._observe_service_settings();self.wait(lambda:self.app.export_dir_var.get()==roots[0])
        self.assertEqual(self.app.screenshot_dir_var.get(),roots[1]);self.assertFalse(self.app.apply_export_dir())

    def test_unauthorized_session_blocks_new_formal_submission_and_keeps_draft(self):
        self.app._svc_client.logout();self.app._service_submit('query',lambda:self.app._svc_client.request('GET','/v1/me'),lambda _:self.fail('unauthorized callback'))
        self.wait(lambda:not self.app._svc_jobs.tasks);self.assertFalse(self.app._storage_valid)
        self.assertEqual(self.app.user_name.get(),'客户')

    def test_same_calculated_draft_submit_button_does_not_book_second_order(self):
        self.app._svc_snapshot=QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),));self.app._svc_details=DraftDetails()
        self.app._svc_result={'status':'ok'};before=self.host.service.ledger.inventory()['counts']['orders']
        self.app.export_to_excel();self.wait(lambda:self.app._svc_submitted is not None and not self.app._svc_jobs.tasks)
        self.assertFalse(self.app.export_to_excel());self.assertEqual(self.host.service.ledger.inventory()['counts']['orders'],before+1)
        self.app.quote_input_changed();self.assertIsNone(self.app._svc_submitted)


if __name__=='__main__':unittest.main()
