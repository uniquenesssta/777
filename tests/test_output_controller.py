"""Current GUI commands through real HTTPS, with headless UI adapters."""
import time
import unittest
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_service_controller import Controller
from service_fixture import Hosted
from quote_core import QuoteSnapshot,NormalLine,DraftDetails
from quote_service.journal import MemoryJournal


class OutputControllerTests(unittest.TestCase):
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
    def order(self):return self.app._svc_client.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),)),DraftDetails(),MemoryJournal())
    def test_selected_order_export_command_creates_task_and_never_books_again(self):
        order=self.order();self.app.refresh_excel_files();self.wait(lambda:not self.app._svc_jobs.tasks)
        self.app.service_order_tree.selection_set(order['order_id']);before=self.host.service.ledger.inventory()
        self.app.request_service_output('excel_quote');self.wait(lambda:not self.app._svc_jobs.tasks)
        self.assertEqual(self.host.service.ledger.inventory(),before)
        self.assertTrue(any(row['order_id']==order['order_id'] for row in self.app._svc_client.request('GET','/v1/outputs')['jobs']))
    def test_current_draft_image_requires_submit_and_uses_that_receipt_only(self):
        before=self.host.service.ledger.inventory();self.assertFalse(self.app.save_screenshot());self.assertEqual(self.host.service.ledger.inventory(),before)
        order=self.order();self.app._svc_submitted=order;self.app.save_screenshot();self.wait(lambda:not self.app._svc_jobs.tasks)
        self.assertTrue(any(row['order_id']==order['order_id'] and row['kind']=='quote_png' for row in self.app._svc_client.request('GET','/v1/outputs')['jobs']))
    def test_search_command_displays_only_matching_scoped_orders_and_totals(self):
        from quote_app.background import Value
        order=self.order();self.app._svc_search=Value(order['order_id']);self.app.refresh_excel_files();self.wait(lambda:not self.app._svc_jobs.tasks)
        self.assertEqual(set(self.app._svc_orders),{order['order_id']});self.assertTrue(any('有效收入' in value for value,_ in self.app.feedback))
