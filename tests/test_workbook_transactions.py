"""Actual current entrypoints plus shared workbook protocol, synthetic data only."""
import json
import multiprocessing as mp
from pathlib import Path
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import uuid

from test_application_integration import application
from quote_app.integration import QuoteApplicationMixin
from quote_files import transactions as tx
from quote_files.workbooks import (assign_order, inspect_receipt, open_book,
    receipts, request, table, target_order, workbook_transaction)


def bind_view(app, path, row=7):
    app.current_excel_path = str(path)
    app.excel_sheet_var = tk.StringVar(app.root, "利润明细")
    app.get_selected_excel_row_index = lambda: row
    book = app.read_excel_view(str(path), "利润明细")
    book.close()
    app.load_current_excel_sheet = Mock()


def export_one(app):
    app.add_fixture_row(product="P02面积")
    app.user_name.set("同秒同客户")
    app.calculate(notify=False)
    path = app.export_to_excel()
    if not path:
        raise AssertionError(app.feedback)
    return Path(path)


def mixed_worker(path, base_headers, operation, order_id, start, output):
    req = request(operation, {"synthetic": operation}, order_id=order_id)
    start.wait(10)
    class Summary:
        find_excel_table_header = staticmethod(table)
    for attempt in range(500):
        try:
            before = tx.read_bytes(path)
            def mutate(book, ws, headers):
                if operation == 'append_quote':
                    first = ws.max_row + 1
                    for source in (7, 8):
                        values = [cell.value for cell in ws[source]]
                        values[headers['记录状态'] - 1] = 'active'
                        ws.append(values)
                    assign_order(ws, first, ws.max_row, headers, req)
                    version = 1
                else:
                    rows = target_order(ws, headers, order_id, 1)
                    for index in rows:
                        ws.cell(index, headers['订单版本'], 2)
                        if operation == 'void_order':
                            ws.cell(index, headers['记录状态'], 'void')
                    if operation == 'append_remark':
                        notes = book.create_sheet('订单备注')
                        notes.append(['请求ID', '订单ID', '备注'])
                        notes.append([req.request_id, order_id, '合成备注'])
                    version = 2
                QuoteApplicationMixin.recompute_daily_profit_summary(Summary(), ws)
                return {'order_revision': version}
            def no_create():
                raise AssertionError('existing file only')
            workbook_transaction(path, req, base_headers, no_create, mutate,
                                 check_hash=operation != 'append_quote', expected_hash=tx.digest(before))
            output.put(('ok', req.request_id))
            return
        except (tx.FileBusy, tx.FileConflict):
            # Explicit synthetic retry: reload a known-not-submitted view only.
            time.sleep(.01)
        except Exception as exc:
            output.put(('error', type(exc).__name__, str(exc)))
            return
    output.put(('error', 'retry deadline'))


class WorkbookTransactionTests(unittest.TestCase):
    def test_same_calculation_double_click_has_one_receipt_and_stable_ids(self):
        for role in ('manager', 'sales'):
            with application(role) as (app, *_):
                path = export_one(app)
                rid = app.last_file_transaction.request_id
                before = path.read_bytes()
                self.assertEqual(Path(app.export_to_excel()), path)
                self.assertTrue(app.last_file_transaction.already_committed)
                self.assertEqual(path.read_bytes(), before)
                book = open_book(before)
                try:
                    ws = book['利润明细']
                    _, headers = table(ws)
                    orders = {ws.cell(i, headers['订单ID']).value for i in (7, 8)}
                    lines = {ws.cell(i, headers['明细ID']).value for i in (7, 8)}
                    self.assertEqual(len(orders), 1)
                    self.assertEqual(len(lines), 2)
                    self.assertEqual(ws.cell(7, headers['请求ID']).value, rid)
                    self.assertEqual(len(receipts(book)), 1)
                    self.assertEqual(book['_写入事务'].sheet_state, 'hidden')
                finally:
                    book.close()

    def test_recalculate_same_second_same_customer_creates_distinct_orders(self):
        with application('manager') as (app, *_):
            with patch('quote_app.integration.time.strftime', side_effect=lambda fmt: '20261011' if fmt == '%Y%m%d' else '2026-10-11 12:00:00'):
                path = export_one(app)
                app.calculate(notify=False)
                self.assertTrue(app.export_to_excel())
            book = open_book(path.read_bytes())
            try:
                _, h = table(book['利润明细'])
                self.assertNotEqual(book['利润明细'].cell(7, h['订单ID']).value, book['利润明细'].cell(9, h['订单ID']).value)
                self.assertEqual(len(receipts(book)), 2)
            finally:
                book.close()

    def test_remark_then_void_preserves_raw_amounts_and_excludes_void_summary(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            bind_view(app, path)
            committed = app._edit_order('append_remark', '=1+1')
            self.assertEqual(committed.result['order_revision'], 2)
            bind_view(app, path)
            app._edit_order('void_order', reason='合成检查：撤销订单')
            book = open_book(path.read_bytes())
            try:
                ws = book['利润明细']
                _, h = table(ws)
                self.assertEqual(ws.max_row, 8)
                self.assertEqual(ws.cell(7, h['销售额']).value, '12.00')
                self.assertEqual(ws.cell(7, h['记录状态']).value, 'void')
                self.assertEqual(ws.cell(8, h['订单版本']).value, 3)
                self.assertEqual(ws.cell(4, 2).value, '0.00')
                self.assertEqual(ws.cell(8, h['备注']).value, '=1+1')
                self.assertEqual(ws.cell(8, h['备注']).data_type, 's')
                self.assertEqual(book['订单备注'].cell(2, 3).data_type, 's')
                self.assertEqual(len(receipts(book)), 3)
            finally:
                book.close()
            bind_view(app, path)
            before = path.read_bytes()
            with self.assertRaises(tx.FileFailure):
                app._edit_order('void_order', reason='合成检查：撤销订单')
            self.assertEqual(path.read_bytes(), before)

    def test_stale_row_view_rejects_instead_of_changing_other_order(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            bind_view(app, path)
            app.calculate(notify=False)
            app.export_to_excel()
            before = path.read_bytes()
            with self.assertRaises(tx.FileConflict):
                app._edit_order('append_remark', '旧页面')
            self.assertEqual(path.read_bytes(), before)
            bind_view(app, path)
            app._edit_order('append_remark', '刷新后')
            book = open_book(path.read_bytes())
            try:
                _, h = table(book['利润明细'])
                self.assertEqual(book['利润明细'].cell(8, h['备注']).value, '刷新后')
                self.assertIsNone(book['利润明细'].cell(10, h['备注']).value)
            finally:
                book.close()

    def test_switch_file_or_failed_view_invalidates_old_edit_lease(self):
        with application('manager') as (app, folder, *_):
            path = export_one(app)
            bind_view(app, path)
            other = folder / 'other.xlsx'
            other.write_bytes(path.read_bytes())
            app.current_excel_path = str(other)
            with self.assertRaises(tx.FileFailure):
                app._edit_order('void_order', reason='合成检查：撤销订单')
            with self.assertRaises(Exception):
                app.read_excel_view(folder / 'missing.xlsx', '利润明细')
            self.assertEqual(app._excel_view_orders, {})
            self.assertIsNone(app._excel_view_path)

    def test_sales_edit_and_entire_file_delete_are_zero_writes(self):
        with application('sales') as (app, *_):
            path = export_one(app)
            bind_view(app, path)
            before = path.read_bytes()
            with self.assertRaises(tx.FileFailure):
                app._edit_order('void_order', reason='合成检查：撤销订单')
            with self.assertRaises(tx.FileFailure):
                app._edit_order('append_remark', '备注')
            self.assertFalse(app.delete_excel_path(path))
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_typed_rows_without_identity_remain_readonly_for_edit(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            book = open_book(path.read_bytes())
            try:
                ws = book['利润明细']
                ws.delete_cols(28, 5)
                del book['订单价格快照']
                book['输入问题'].delete_cols(7, 2)
                del book['_写入事务']
                book.save(path)
            finally:
                book.close()
            bind_view(app, path)
            before = path.read_bytes()
            with self.assertRaises(tx.FileFailure):
                app._edit_order('void_order', reason='合成检查：撤销订单')
            self.assertEqual(path.read_bytes(), before)
            app.calculate(notify=False)
            self.assertTrue(app.export_to_excel())  # New identified order only.
            book = open_book(path.read_bytes())
            try:
                _, h = table(book['利润明细'])
                self.assertIsNone(book['利润明细'].cell(7, h['订单ID']).value)
                self.assertIsNotNone(book['利润明细'].cell(9, h['订单ID']).value)
            finally:
                book.close()

    def test_sales_view_uses_order_ids_for_same_second_and_hides_void(self):
        with application('manager') as (manager, *_):
            with patch('quote_app.integration.time.strftime', side_effect=lambda fmt: '20261011' if fmt == '%Y%m%d' else '2026-10-11 12:00:00'):
                path = export_one(manager)
                manager.calculate(notify=False)
                manager.export_to_excel()
            with application('sales') as (sales, *_):
                book = open_book(path.read_bytes())
                try:
                    ws = book['利润明细']
                    header_row, h = table(ws)
                    totals = sales.build_group_sales_totals(ws, h, header_row)
                    self.assertEqual(len(totals), 2)
                    self.assertEqual(list(totals.values()), [12.0, 12.0])
                    self.assertTrue(sales.sales_record_visible(ws, h, 7))
                    self.assertFalse(sales.sales_record_visible(ws, h, 8))
                finally:
                    book.close()
                bind_view(manager, path)
                manager._edit_order('void_order', reason='合成检查：撤销订单')
                book = open_book(path.read_bytes())
                try:
                    ws = book['利润明细']
                    header_row, h = table(ws)
                    self.assertFalse(sales.sales_record_visible(ws, h, 7))
                    self.assertTrue(sales.sales_record_visible(ws, h, 9))
                    self.assertEqual(len(sales.build_group_sales_totals(ws, h, header_row)), 1)
                finally:
                    book.close()

    def test_unknown_corrupt_or_untyped_daily_file_is_never_rebuilt(self):
        for kind in ('bad_zip', 'unknown_sheet', 'untyped', 'partial_ids', 'invalid_version', 'unknown_column', 'unknown_price_snapshot'):
            with self.subTest(kind=kind), application('manager') as (app, *_):
                path = export_one(app)
                if kind == 'bad_zip':
                    path.write_bytes(b'not a workbook')
                else:
                    book = open_book(path.read_bytes())
                    try:
                        if kind == 'unknown_sheet':
                            book.create_sheet('未知数据')
                        elif kind == 'untyped':
                            book['利润明细'].cell(7, 27).value = None
                        elif kind == 'unknown_column':
                            book['利润明细'].cell(6, 33, '未知列')
                        elif kind == 'unknown_price_snapshot':
                            book['价格设定'].cell(4, 1, '未知格式')
                        elif kind == 'partial_ids':
                            book['利润明细'].delete_cols(29)
                        else:
                            book['利润明细'].cell(7, 30, 9)
                        book.save(path)
                    finally:
                        book.close()
                before = path.read_bytes()
                app.calculate(notify=False)
                self.assertFalse(app.export_to_excel())
                self.assertEqual(path.read_bytes(), before)

    def test_committed_edit_refresh_error_and_retry_do_not_duplicate_note(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            bind_view(app, path)
            app.load_current_excel_sheet.side_effect = OSError('synthetic refresh error')
            first = app._edit_order('append_remark', '只追加一次')
            self.assertIn('已保存', app.feedback)
            again = app._edit_order('append_remark', '只追加一次')
            self.assertTrue(again.already_committed)
            self.assertEqual(first.request_id, again.request_id)
            book = open_book(path.read_bytes())
            try:
                self.assertEqual(book['订单备注'].max_row, 2)
            finally:
                book.close()

    def test_unknown_append_query_then_retry_has_no_duplicate(self):
        with application('manager') as (app, *_):
            app.add_fixture_row()
            app.calculate(notify=False)
            original = tx.read_bytes
            target = Path(app.get_daily_excel_path())
            count = 0
            def read(path):
                nonlocal count
                if Path(path) == target:
                    count += 1
                    if count >= 3:
                        raise OSError('synthetic disconnect')
                return original(path)
            with patch.object(tx, 'read_bytes', side_effect=read):
                self.assertFalse(app.export_to_excel())
            rid = app._excel_pending['request'].request_id
            self.assertTrue(app._excel_pending['unknown'])
            self.assertIn(rid, app.feedback)
            self.assertEqual(app.check_last_write()['status'], 'committed')
            self.assertTrue(app.export_to_excel())
            book = open_book(target.read_bytes())
            try:
                self.assertEqual(len(receipts(book)), 1)
            finally:
                book.close()

    def test_prior_unknown_journal_queries_prior_id_and_blocks_new_requests(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            prior_id = str(uuid.uuid4())
            prior = tx.journal_path(path, prior_id)
            prior.write_text(json.dumps({'state': 'prepared', 'request_id': prior_id,
                'fingerprint': 'a' * 64, 'before_sha256': 'b' * 64,
                'after_sha256': 'c' * 64, 'result': {'fingerprint': 'a' * 64}}))
            before = path.read_bytes()
            app.calculate(notify=False)
            self.assertFalse(app.export_to_excel())
            self.assertIn(prior_id, app.feedback)
            self.assertEqual(app._blocking_file_request['request_id'], prior_id)
            self.assertEqual(app.check_last_write()['status'], 'unknown')
            self.assertIn(prior_id, app.feedback)
            app.calculate(notify=False)
            self.assertFalse(app.export_to_excel())
            self.assertEqual(path.read_bytes(), before)

    def test_listing_workbook_closes_when_sheet_enumeration_raises(self):
        for role in ('manager', 'sales'):
            with application(role) as (app, folder, ns, *_):
                path = folder / 'dummy.xlsx'
                path.write_bytes(b'synthetic')
                class BrokenBook:
                    close = Mock()
                    @property
                    def worksheets(self):
                        raise OSError('synthetic enumeration failure')
                broken = BrokenBook()
                with patch.object(app, 'open_excel_for_view', return_value=broken):
                    app.open_excel_path(str(path))
                broken.close.assert_called_once()

    def test_concurrent_append_remark_void_preserve_all_receipts_and_amounts(self):
        with application('manager') as (app, *_):
            path = export_one(app)
            app.calculate(notify=False)
            app.export_to_excel()
            book = open_book(path.read_bytes())
            try:
                _, h = table(book['利润明细'])
                first = book['利润明细'].cell(7, h['订单ID']).value
                second = book['利润明细'].cell(9, h['订单ID']).value
            finally:
                book.close()
            ctx = mp.get_context('spawn')
            start, output = ctx.Event(), ctx.Queue()
            specs = [('append_quote', str(uuid.uuid4())), ('append_remark', first), ('void_order', second)]
            children = [ctx.Process(target=mixed_worker, args=(str(path), app.get_excel_headers(), op, oid, start, output)) for op, oid in specs]
            try:
                for child in children:
                    child.start()
                start.set()
                results = [output.get(timeout=30) for _ in children]
                for child in children:
                    child.join(10)
                self.assertEqual([r[0] for r in results], ['ok'] * 3, results)
                book = open_book(path.read_bytes())
                try:
                    ws = book['利润明细']
                    self.assertEqual(len(receipts(book)), 5)
                    self.assertEqual(ws.max_row, 12)
                    self.assertEqual(ws.cell(4, 2).value, '24.00')
                    self.assertEqual(ws.cell(4, 4).value, '8.00')
                    self.assertEqual(ws.cell(4, 6).value, '16.00')
                    self.assertEqual(book['订单备注'].cell(2, 2).value, first)
                    self.assertEqual(ws.cell(9, h['记录状态']).value, 'void')
                finally:
                    book.close()
            finally:
                for child in children:
                    if child.is_alive():
                        child.terminate()
                    child.join(5)
                output.close()


if __name__ == '__main__':
    unittest.main()
