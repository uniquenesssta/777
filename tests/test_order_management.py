"""P03-04 order lifecycle, history ownership, cancellation and failure boundaries."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import uuid

from test_application_integration import application
from test_workbook_transactions import bind_view, export_one
from quote_files import transactions as tx
from quote_files.reading import read_ledger
from quote_files.workbooks import open_book, table


class TextBuffer:
    def __init__(self):
        self.text, self.state = "", "normal"
    def get(self, *_):
        return self.text
    def delete(self, *_):
        if self.state == "normal":
            self.text = ""
    def insert(self, _, text):
        if self.state == "normal":
            self.text += text
    def configure(self, *, state):
        self.state = state


def display(app, path, row=7):
    bind_view(app, path, row)
    if not hasattr(app, "excel_remark_text"):
        app.excel_remark_text = TextBuffer()
        app.excel_order_history = TextBuffer()
        app.excel_order_label = tk.StringVar(app.root)
        app.excel_order_reason = tk.StringVar(app.root)
        app.excel_void_button, app.excel_restore_button, app.excel_note_button = Mock(), Mock(), Mock()
    return app.load_current_excel_remark()


def edit_file(path, mutate):
    book = open_book(path.read_bytes())
    try:
        mutate(book)
        book.save(path)
    finally:
        book.close()


class OrderManagementTests(unittest.TestCase):
    def test_order_history_and_unsaved_drafts_do_not_cross_same_customer_orders(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            app.calculate(notify=False)
            app.export_to_excel()
            first = display(app, path)
            app.excel_remark_text.insert("1.0", "第一单")
            self.assertTrue(app.save_current_excel_remark())
            display(app, path)
            app.excel_remark_text.insert("1.0", "第一单未保存草稿")
            second = display(app, path, 9)
            self.assertNotEqual(first.order_id, second.order_id)
            self.assertNotIn("第一单", app.excel_order_history.text)
            self.assertEqual(app.excel_remark_text.text, "")
            app.excel_remark_text.insert("1.0", "第二单")
            app.save_current_excel_remark()
            display(app, path)
            self.assertIn("第一单", app.excel_order_history.text)
            self.assertNotIn("第二单", app.excel_order_history.text)
            self.assertEqual(app.excel_remark_text.text, "第一单未保存草稿")

    def test_append_correction_preserves_original_text_and_request_identity(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            first = display(app, path)
            app._edit_order("append_remark", "=1+1")
            display(app, path)
            app._edit_order("append_remark", "更正：上条作废，以本条为准")
            view = display(app, path)
            self.assertEqual(view.order_id, first.order_id)
            self.assertEqual(tuple(n[1] for n in view.notes), ("=1+1", "更正：上条作废，以本条为准"))
            self.assertEqual(len({n[0] for n in view.notes}), 2)
            book = open_book(path.read_bytes())
            try:
                self.assertEqual(book["订单备注"].cell(2, 3).data_type, "s")
                self.assertEqual(book["订单备注"].max_row, 3)
            finally:
                book.close()

    def test_void_restore_preserve_all_rows_notes_prices_inputs_and_amount_once(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("append_remark", "历史保留")
            original = display(app, path)
            app._edit_order("void_order", reason="客户取消")
            void = display(app, path)
            self.assertEqual(void.state, "void")
            self.assertEqual(read_ledger(path).totals.income_cents, 0)
            self.assertEqual(app.excel_remark_text.state, "disabled")
            self.assertIn("已作废", app.excel_order_label.get())
            app._edit_order("restore_order", reason="客户恢复订单")
            restored = display(app, path)
            self.assertEqual(restored.revision, 4)
            self.assertEqual(restored.state, "active")
            self.assertEqual((restored.notes, restored.prices, restored.inputs), (original.notes, original.prices, original.inputs))
            self.assertEqual(read_ledger(path).totals.income_cents, 1200)
            self.assertEqual([e[1] for e in restored.events], ["append_quote", "append_remark", "void_order", "restore_order"])
            self.assertEqual([e[4] for e in restored.events[-2:]], ["客户取消", "客户恢复订单"])
            book = open_book(path.read_bytes())
            try:
                ws = book["利润明细"]
                _, h = table(ws)
                self.assertEqual(ws.max_row, 8)
                self.assertEqual(ws.cell(7, h["销售额"]).value, "12.00")
                self.assertEqual([ws.cell(i, h["订单版本"]).value for i in (7, 8)], [4, 4])
            finally:
                book.close()

    def test_cancel_void_and_restore_leave_bytes_and_drafts_intact(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            for action, operation in ((app.delete_current_excel_row, "void_order"), (app.restore_current_excel_order, "restore_order")):
                app.excel_order_reason.set("填写但取消")
                before = path.read_bytes()
                with patch("tkinter.messagebox.askyesno", return_value=False):
                    self.assertFalse(action())
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(app.excel_order_reason.get(), "填写但取消")
                app._edit_order(operation, reason="合成前置转换")
                display(app, path)

    def test_reasons_required_for_direct_and_ui_actions_before_writes(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            before = path.read_bytes()
            for operation in ("void_order", "restore_order"):
                for reason in (None, " ", "x" * 4097):
                    with self.assertRaises(tx.FileFailure):
                        app._edit_order(operation, reason=reason)
            with patch("tkinter.messagebox.askyesno") as confirm:
                self.assertFalse(app.delete_current_excel_row())
                confirm.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_confirmation_contains_captured_identity_revision_reason_and_cancel_effect(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            view = display(app, path)
            app.excel_order_reason.set("具体取消原因")
            with patch("tkinter.messagebox.askyesno", return_value=True) as confirm:
                self.assertTrue(app.delete_current_excel_row())
            text = confirm.call_args.args[1]
            for value in (view.order_id, "版本：1", "具体取消原因", "移出有效汇总"):
                self.assertIn(value, text)
            self.assertEqual(app.excel_order_reason.get(), "")

    def test_modal_selection_change_rejects_retargeting_without_touching_either_order(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            app.calculate(notify=False)
            app.export_to_excel()
            display(app, path)
            app.excel_order_reason.set("本次只取消第一单")
            before = path.read_bytes()
            def switch(*_):
                app.get_selected_excel_row_index = lambda: 9
                return True
            with patch("tkinter.messagebox.askyesno", side_effect=switch):
                self.assertFalse(app.delete_current_excel_row())
            self.assertIn("确认期间", app.feedback)
            self.assertEqual(path.read_bytes(), before)

    def test_modal_external_append_rejects_stale_hash(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app.excel_order_reason.set("取消旧页面订单")
            saved = []
            def append(*_):
                app.calculate(notify=False)
                app.export_to_excel()
                saved.append(path.read_bytes())
                return True
            with patch("tkinter.messagebox.askyesno", side_effect=append):
                self.assertFalse(app.delete_current_excel_row())
            self.assertEqual(path.read_bytes(), saved[0])
            self.assertIn("刷新", app.feedback)

    def test_restore_repeated_same_request_is_one_receipt_and_one_amount(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("void_order", reason="取消")
            display(app, path)
            first = app._edit_order("restore_order", reason="恢复")
            before = path.read_bytes()
            second = app._edit_order("restore_order", reason="恢复")
            self.assertTrue(second.already_committed)
            self.assertEqual(first.request_id, second.request_id)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(read_ledger(path).totals.income_cents, 1200)
            self.assertEqual(len(display(app, path).events), 3)

    def test_new_restore_request_on_active_order_refused_without_doubling_amount(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("void_order", reason="取消")
            display(app, path)
            app._edit_order("restore_order", reason="恢复")
            display(app, path)
            before = path.read_bytes()
            with self.assertRaises(tx.FileFailure):
                app._edit_order("restore_order", reason="再次恢复")
            self.assertEqual(path.read_bytes(), before)

    def test_unknown_restore_query_and_same_request_retry_do_not_duplicate(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("void_order", reason="取消")
            display(app, path)
            original = tx.read_bytes
            count = 0
            def read(target):
                nonlocal count
                if str(target) == str(path):
                    count += 1
                    if count >= 3:
                        raise OSError("synthetic readback loss")
                return original(target)
            with patch.object(tx, "read_bytes", side_effect=read):
                with self.assertRaises(tx.UnknownCommit):
                    app._edit_order("restore_order", reason="恢复")
            rid = app._edit_pending["request"].request_id
            self.assertTrue(app._edit_pending["unknown"])
            with self.assertRaises(tx.FileFailure):
                app._edit_order("restore_order", reason="改了原因的新请求")
            self.assertEqual(app.check_last_write()["status"], "committed")
            again = app._edit_order("restore_order", reason="恢复")
            self.assertEqual(again.request_id, rid)
            self.assertTrue(again.already_committed)
            self.assertEqual(len(display(app, path).events), 3)

    def test_refresh_failure_reports_committed_and_restored_amount_not_failure(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("void_order", reason="取消")
            display(app, path)
            app.load_current_excel_sheet.side_effect = OSError("synthetic refresh loss")
            committed = app._edit_order("restore_order", reason="恢复")
            self.assertIn("已保存，刷新失败", app.feedback)
            self.assertIn(committed.request_id, app.feedback)
            self.assertEqual(read_ledger(path).totals.income_cents, 1200)

    def test_stale_restore_after_another_writer_rejected_then_fresh_note_is_correct(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("void_order", reason="取消")
            display(app, path)
            captured = app._edit_target()
            app._edit_order("restore_order", reason="其他母版恢复")
            before = path.read_bytes()
            app._edit_pending = None  # Independent writer/request, same stale view.
            with self.assertRaises(tx.FileConflict):
                app._edit_order("restore_order", reason="旧页面恢复", target=captured)
            self.assertEqual(path.read_bytes(), before)
            display(app, path)
            app._edit_order("append_remark", "核对后继续")
            self.assertEqual(read_ledger(path).totals.income_cents, 1200)

    def test_external_row_reorder_rejects_old_index_then_stable_id_owns_note(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            app.calculate(notify=False)
            app.export_to_excel()
            first = display(app, path)
            def swap(book):
                ws = book["利润明细"]
                values = [[c.value for c in ws[r]] for r in (7, 8, 9, 10)]
                for row, data in zip((7, 8, 9, 10), values[2:] + values[:2]):
                    for col, value in enumerate(data, 1):
                        ws.cell(row, col, value)
            edit_file(path, swap)
            before = path.read_bytes()
            with self.assertRaises(tx.FileConflict):
                app._edit_order("append_remark", "旧索引不可写")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(display(app, path, 9).order_id, first.order_id)
            app._edit_order("append_remark", "按编号找回的第一单")
            self.assertEqual(display(app, path, 9).notes[0][1], "按编号找回的第一单")
            self.assertEqual(display(app, path, 7).notes, ())

    def test_blank_customer_and_reference_order_remains_manageable_by_id(self):
        with application("manager") as (app, *_):
            app.add_fixture_row(product="P02面积")
            app.calculate(notify=False)
            path = app.export_to_excel()
            from pathlib import Path
            path = Path(path)
            view = display(app, path)
            self.assertTrue(view.order_id)
            app._edit_order("void_order", reason="空客户单也可管理")
            display(app, path)
            app._edit_order("restore_order", reason="核对恢复")
            self.assertEqual(read_ledger(path).totals.income_cents, 1200)

    def test_unknown_operation_and_sales_restore_refused_with_zero_writes(self):
        for role in ("manager", "sales"):
            with application(role) as (app, *_):
                path = export_one(app)
                bind_view(app, path)
                before = path.read_bytes()
                with self.assertRaises(tx.FileFailure):
                    app._edit_order("permanent_delete", "不能被当备注")
                if role == "sales":
                    with self.assertRaises(tx.FileFailure):
                        app._edit_order("restore_order", reason="子版不可恢复")
                self.assertEqual(path.read_bytes(), before)

    def test_invalid_selection_or_switch_sheet_clears_history_and_disables_actions(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("append_remark", "订单历史")
            display(app, path)
            self.assertIn("订单历史", app.excel_order_history.text)
            app.excel_sheet_var.set("输入问题")
            self.assertIsNone(app.load_current_excel_remark())
            self.assertEqual(app.excel_order_history.text, "")
            self.assertEqual(app.excel_remark_text.state, "disabled")
            app.excel_restore_button.configure.assert_called_with(state="disabled")

    def test_file_level_legacy_remark_is_never_attached_to_selected_order(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            edit_file(path, lambda book: book.create_sheet("备注").cell(5, 2, "文件说明归属未知"))
            view = display(app, path)
            self.assertEqual(view.notes, ())
            self.assertNotIn("文件说明归属未知", app.excel_order_history.text)
            self.assertIn("LEGACY_FILE_REMARK", [i.code for i in read_ledger(path).issues])

    def test_association_corruption_rejects_append_without_rewriting_original(self):
        for sheet, column in (("订单备注", 2), ("订单价格快照", 1), ("输入问题", 7)):
            with self.subTest(sheet=sheet), application("manager") as (app, *_):
                path = export_one(app)
                bind_view(app, path)
                app._edit_order("append_remark", "原备注")
                row = 5 if sheet == "输入问题" else 2
                edit_file(path, lambda book: book[sheet].cell(row, column, str(uuid.uuid4())))
                before = path.read_bytes()
                self.assertEqual(read_ledger(path).status, "error")
                app.calculate(notify=False)
                self.assertFalse(app.export_to_excel())
                self.assertEqual(path.read_bytes(), before)

    def test_duplicate_note_request_rejected_without_silent_overwrite(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            display(app, path)
            app._edit_order("append_remark", "原备注")
            edit_file(path, lambda book: book["订单备注"].append([c.value for c in book["订单备注"][2]]))
            before = path.read_bytes()
            self.assertEqual(read_ledger(path).status, "error")
            app.calculate(notify=False)
            self.assertFalse(app.export_to_excel())
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_input_rows_preserved_without_fabricating_owner(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            def legacy(book):
                book["输入问题"].delete_cols(7, 2)
            edit_file(path, legacy)
            before = open_book(path.read_bytes())
            old_row = tuple(c.value for c in before["输入问题"][5])
            before.close()
            app.calculate(notify=False)
            app.export_to_excel()
            first = display(app, path)
            second = display(app, path, 9)
            self.assertEqual(first.inputs, ())
            self.assertEqual(len(second.inputs), 1)
            book = open_book(path.read_bytes())
            try:
                self.assertEqual(tuple(c.value for c in book["输入问题"][5][:6]), old_row)
                self.assertIsNone(book["输入问题"].cell(5, 7).value)
                self.assertEqual(book["输入问题"].cell(6, 7).value, second.order_id)
            finally:
                book.close()

    def test_unknown_gui_check_is_blocked_off_windows_and_never_launches_tk(self):
        import p03_order_check as check
        with patch.object(check.platform, "system", return_value="Linux"), patch.object(check, "run_checks", return_value={"status": "passed"}), patch.object(check.gui, "run_pair") as pair, patch("baseline_check.emit"):
            self.assertEqual(check.main(["--gui-smoke"]), 2)
            pair.assert_not_called()


if __name__ == "__main__":
    unittest.main()
