"""Synthetic blocking I/O + real Tcl owner variables; no Windows timing claims."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
from threading import Event, get_ident
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from test_application_integration import application
from test_workbook_transactions import export_one, bind_view
from quote_app.background import BackgroundApplicationMixin, capture, run
from quote_app.jobs import Jobs, QueueFull
from quote_files.reading import read_ledger
from quote_files.metadata import file_version


def wait_for(predicate, pump=lambda: None, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("synthetic task deadline exceeded")


class Tree:
    def __init__(self):
        self.rows, self.selected = {}, ()
    def get_children(self):return tuple(self.rows)
    def delete(self, *items):
        for item in items:self.rows.pop(item, None)
    def insert(self, *_args, iid, values):self.rows[iid] = tuple(values)
    def selection(self):return self.selected
    def selection_set(self, item):self.selected = (item,)
    def see(self, *_):pass
    def configure(self, **_):pass
    def heading(self, *_args, **_kwargs):pass
    def column(self, *_args, **_kwargs):pass


@contextmanager
def asynchronous(app):
    class Async(type(app)):
        refresh_excel_files = BackgroundApplicationMixin.refresh_excel_files
        def show_excel_detail(self):pass
    app.__class__ = Async
    app.initialize_background_io()
    original_poll = app._poll_io
    def pump():
        app.root.after_cancel(app._io_poll_job)
        original_poll()
    app._poll_io = pump
    app.excel_file_tree, app.excel_view_tree = Tree(), Tree()
    app.excel_sheet_combo = Mock()
    for name in ("excel_selected_file", "excel_sheet_var", "excel_total_count", "excel_total_income", "excel_total_cost", "excel_total_profit", "excel_total_margin"):
        setattr(app, name, tk.StringVar(app.root))
    try:
        yield app
    finally:
        app._io_runtime.cancel_reads()
        wait_for(lambda: not app._io_runtime.writing, lambda: app._poll_io())
        app._io_runtime.close()
        for job in (app._io_poll_job, *tuple(app._after_jobs)):
            app.root.after_cancel(job)
        app._after_jobs.clear()
        if not app._io_runtime.wait_closed(5):
            raise AssertionError("诊断读线程尚未退出，不能清理临时数据")


class JobsTests(unittest.TestCase):
    def test_diagnostic_wait_requires_closed_queue_and_timeout_does_not_terminate_reader(self):
        jobs = Jobs(readers=1)
        started, release = Event(), Event()
        try:
            with self.assertRaises(RuntimeError):jobs.wait_closed(.01)
            task = jobs.submit("read", lambda ctx: (started.set(), release.wait(3)))
            self.assertTrue(started.wait(1))
            jobs.close()
            self.assertFalse(jobs.wait_closed(.01))
            self.assertEqual(task.state, "running")
            release.set()
            self.assertTrue(jobs.wait_closed(1))
            self.assertEqual(task.state, "cancelled")
        finally:
            release.set();jobs.close()
            self.assertTrue(jobs.wait_closed(1))

    def test_reader_queue_is_bounded_while_native_call_is_still_blocked(self):
        jobs = Jobs(readers=1, capacity=1)
        started, release = Event(), Event()
        def blocked(ctx):started.set();release.wait(2);return 1
        try:
            jobs.submit("one", blocked)
            self.assertTrue(started.wait(1))
            jobs.submit("two", lambda ctx: 2)
            with self.assertRaises(QueueFull):jobs.submit("three", lambda ctx: 3)
        finally:
            release.set();jobs.cancel_reads();jobs.close()

    def test_latest_task_supersedes_queued_task_without_running_it(self):
        jobs = Jobs(readers=1)
        started, release = Event(), Event()
        ran = []
        try:
            jobs.submit("hold", lambda ctx: (started.set(), release.wait(2)))
            self.assertTrue(started.wait(1))
            old = jobs.submit("files", lambda ctx: ran.append("old"))
            newest = jobs.submit("files", lambda ctx: ran.append("new"))
            release.set()
            wait_for(lambda: newest.state == "completed")
            self.assertEqual(ran, ["new"])
            self.assertFalse(jobs.current(old))
        finally:release.set();jobs.close()

    def test_timeout_does_not_free_running_slot_or_claim_io_terminated(self):
        jobs = Jobs(readers=1, timeout=.02)
        started, release = Event(), Event()
        try:
            task = jobs.submit("read", lambda ctx: (started.set(), release.wait(2)))
            self.assertTrue(started.wait(1))
            events = []
            wait_for(lambda: any(e[1] == "timeout" for e in events), lambda: events.extend(jobs.drain()))
            self.assertEqual(task.state, "running")
            self.assertIn(task.number, jobs.tasks)
            self.assertFalse(jobs.current(task))
        finally:release.set();jobs.close()

    def test_write_is_serial_not_cancellable_and_result_delivered_before_close(self):
        jobs = Jobs(timeout=.02)
        started, release = Event(), Event()
        try:
            task = jobs.submit("write", lambda ctx: (started.set(), release.wait(2), "receipt")[-1], write=True)
            self.assertTrue(started.wait(1))
            jobs.cancel_reads()
            self.assertFalse(task.cancelled.is_set())
            with self.assertRaises(QueueFull):jobs.submit("another", lambda ctx: None, write=True)
            with self.assertRaises(RuntimeError):jobs.close()
            release.set();wait_for(lambda: task.state == "completed")
            self.assertTrue(jobs.writing)  # Still awaiting owner delivery.
            self.assertEqual([e[2] for e in jobs.drain() if e[1] == "completed"], ["receipt"])
            self.assertFalse(jobs.writing)
            jobs.close()
        finally:release.set()


class BackgroundAdapterTests(unittest.TestCase):
    def test_both_calculation_pages_wire_export_control_to_background_commit(self):
        from tkinter import ttk
        import p04_io_check as check
        for role in ("manager", "sales"):
            with self.subTest(role=role), application(role) as (app, folder, ns, _):
                path = export_one(app);app.calculate(notify=False)
                with asynchronous(app), ExitStack() as widgets:
                    app.calc_page = Mock()
                    app.feedback_var = tk.StringVar(app.root)
                    controls = {}
                    def button(*args, **kwargs):
                        control = Mock()
                        control.invoke = kwargs["command"]
                        control.cget.side_effect = lambda name: kwargs.get(name, "normal")
                        controls[kwargs["text"]] = control
                        return control
                    for module, names in ((ttk, ("Frame", "LabelFrame", "Label", "Entry", "Combobox")), (tk, ("Frame", "Label"))):
                        for name in names:
                            widgets.enter_context(patch.object(module, name, side_effect=lambda *a, **k: Mock()))
                    widgets.enter_context(patch.object(ttk, "Button", side_effect=button))
                    widgets.enter_context(patch.dict(ns, {"ScrollableFrame": lambda *a, **k: Mock()}))
                    app.setup_calc_page()
                    self.assertIs(app.calc_export_button, controls["导出 Excel"])
                    task = check.invoke_write_control(app, app.calc_export_button)
                    wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                    self.assertEqual(read_ledger(path).totals.income_cents, 2400)
                    self.assertIsNotNone(app.last_file_transaction)
                    self.assertIs(app.calc_quote_image_button, controls["保存完整报价图"])
                    self.assertIs(app.calc_screenshot_button, controls["保存窗口截图"])
                    image_task = check.invoke_write_control(app,app.calc_quote_image_button)
                    wait_for(lambda:image_task.number not in app._io_callbacks,app._poll_io)
                    import json
                    image_manifest = json.loads(Path(app.last_file_transaction.path).read_text())
                    self.assertEqual(image_manifest['line_count'],1)
                    self.assertEqual(image_manifest['totals']['销售额'],'12.00')
                    self.assertEqual(read_ledger(path).totals.income_cents,2400)

    def test_gui_write_probe_rejects_disabled_control_or_reused_task(self):
        import p04_io_check as check
        app, control = Mock(), Mock()
        app._io_runtime.latest = {"write": object()}
        control.cget.return_value = "disabled"
        with self.assertRaises(AssertionError):check.invoke_write_control(app, control)
        control.invoke.assert_not_called()
        control.cget.return_value = "normal"
        with self.assertRaises(AssertionError):check.invoke_write_control(app, control)
        control.invoke.assert_called_once()

    def test_diagnostic_teardown_finishes_unobserved_reader_before_sandbox_cleanup(self):
        started, release, finished = Event(), Event(), Event()
        jobs = None
        try:
            with application("manager") as (app, folder, *_), ExitStack() as patches:
                with asynchronous(app):
                    jobs = app._io_runtime
                    original_wait = jobs.wait_closed
                    def release_before_join(timeout):
                        release.set()
                        return original_wait(timeout)
                    def holding_file(ctx):
                        with (folder / "storage.json").open("rb") as stream:
                            started.set();release.wait(3);stream.read()
                        finished.set()
                    patches.enter_context(patch.object(jobs, "wait_closed", side_effect=release_before_join))
                    task = jobs.submit("follow_up_scan", holding_file)
                    self.assertTrue(started.wait(1))
                    self.assertFalse(finished.is_set())
                self.assertTrue(finished.is_set())
                self.assertEqual(task.state, "cancelled")
            self.assertFalse(folder.exists())
        finally:
            release.set()
            if jobs is not None:
                jobs.close();jobs.wait_closed(1)

    def test_real_entrypoint_worker_reads_prices_without_touching_any_tk_variable(self):
        for role in ("manager", "sales"):
            with self.subTest(role=role), application(role) as (app, *_), asynchronous(app):
                owner = get_ident()
                threads = []
                with ExitStack() as patches:
                    for kind in (tk.StringVar, tk.BooleanVar):
                        original = kind.get
                        def get(var, fn=original):threads.append(get_ident());return fn(var)
                        patches.enter_context(patch.object(kind, "get", get))
                    task = app.reload_price_settings_from_json(silent=True)
                    wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                self.assertTrue(threads)
                self.assertEqual(set(threads), {owner})
                self.assertTrue(app.active_price_config)

    def test_slow_excel_scan_does_not_block_editing_or_tcl_owner_heartbeat(self):
        with application("manager") as (app, *_):
            export_one(app)
            with asynchronous(app):
                started, release = Event(), Event()
                original = file_version
                def slow(path):started.set();release.wait(2);return original(path)
                try:
                    with patch("quote_files.cache.file_version", side_effect=slow):
                        task = app.refresh_excel_files()
                        self.assertTrue(started.wait(1))
                        app.user_name.set("扫描中编辑")
                        heartbeat = []
                        app.root.after(0, lambda: heartbeat.append(True))
                        app.root.eval("update")
                        self.assertEqual(heartbeat, [True])
                        self.assertEqual(app.user_name.get(), "扫描中编辑")
                        release.set();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                    self.assertEqual(len(app.excel_file_tree.rows), 1)
                finally:release.set()

    def test_cancel_scan_prevents_late_rows_from_overwriting_last_verified_list(self):
        with application("manager") as (app, *_):
            export_one(app)
            with asynchronous(app):
                first = app.refresh_excel_files();wait_for(lambda: first.number not in app._io_callbacks, app._poll_io)
                original_rows = dict(app.excel_file_tree.rows)
                started, release = Event(), Event()
                original = file_version
                def slow(path):started.set();release.wait(2);return original(path)
                try:
                    with patch("quote_files.cache.file_version", side_effect=slow):
                        task = app.refresh_excel_files();self.assertTrue(started.wait(1))
                        app.cancel_background_reads();release.set()
                        wait_for(lambda: task.number not in app._io_runtime.tasks, app._poll_io)
                    self.assertEqual(app.excel_file_tree.rows, original_rows)
                finally:release.set()

    def test_directory_epoch_discards_old_scan_after_source_change(self):
        with application("manager") as (app, folder, *_):
            path = export_one(app)
            new_root = folder / "新的数据源"
            new_root.mkdir();(new_root / "reports").mkdir();(new_root / "screenshots").mkdir()
            for name in ("config.json", "storage.json"):
                (new_root / name).write_bytes((folder / name).read_bytes())
            with asynchronous(app):
                started, release = Event(), Event()
                original = file_version
                def slow(path):started.set();release.wait(2);return original(path)
                try:
                    with patch("quote_files.cache.file_version", side_effect=slow):
                        task = app.refresh_excel_files();self.assertTrue(started.wait(1))
                        app.excel_total_income.set("12.00")
                        app.data_source_var.set(str(new_root))
                        change = app.apply_connection()
                        wait_for(lambda: change.number not in app._io_callbacks, app._poll_io)
                        self.assertEqual(app.data_root, str(new_root))
                        self.assertEqual(app.excel_total_income.get(), "—")
                        self.assertEqual(app.excel_selected_file.get(), "目录已切换，请重新选择文件。")
                        release.set();wait_for(lambda: task.number not in app._io_runtime.tasks, app._poll_io)
                    self.assertEqual(app.excel_file_tree.rows, {})
                    self.assertEqual(read_ledger(path).totals.income_cents, 1200)
                finally:release.set()

    def test_price_reload_does_not_overwrite_user_editor_changed_during_read(self):
        with application("manager") as (app, *_), asynchronous(app):
            started, release = Event(), Event()
            original = app.__class__._read_price_candidate
            def slow(worker):started.set();release.wait(2);return original(worker)
            try:
                with patch.object(app.__class__, "_read_price_candidate", slow):
                    task = app.reload_price_settings_from_json(silent=True);self.assertTrue(started.wait(1))
                    app.setting_rows[0]["sale"].set("123")
                    changed = app.quote_session.state.revision
                    release.set();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                self.assertEqual(app.setting_rows[0]["sale"].get(), "123")
                self.assertIn("保留当前草稿", app.feedback)
                self.assertGreaterEqual(app.quote_session.state.revision, changed)
            finally:release.set()

    def test_background_excel_commit_uses_frozen_quote_not_later_widget_edits(self):
        with application("manager") as (app, *_):
            path = export_one(app)
            app.calculate(notify=False)
            with asynchronous(app):
                started, release = Event(), Event()
                original = app.__class__._observe_price_file
                def slow(worker):started.set();release.wait(2);return original(worker)
                try:
                    with patch.object(app.__class__, "_observe_price_file", slow):
                        task = app.export_to_excel();self.assertTrue(started.wait(1))
                        app.calc_rows[0]["q"].set("2")
                        changed = app.quote_session.state.revision
                        release.set();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                    self.assertEqual(read_ledger(path).totals.income_cents, 2400)
                    self.assertEqual(app.quote_session.state.revision, changed)
                    self.assertIsNone(app.quote_session.state.result)
                    self.assertIsNotNone(app.last_file_transaction)
                finally:release.set()

    def test_background_view_keeps_stable_edit_lease_and_sales_projection(self):
        for role in ("manager", "sales"):
            with self.subTest(role=role), application(role) as (app, *_):
                path = export_one(app)
                with asynchronous(app):
                    task = app.open_excel_path(str(path))
                    wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                    self.assertEqual(len(app.excel_view_tree.rows), 8 if role == "manager" else 1)
                    self.assertEqual(app._excel_view_path, str(path.absolute()))
                    self.assertTrue(app._excel_view_orders)

    def test_cold_start_restores_connection_in_worker_then_delivers_owner_prices(self):
        with application("manager") as (app, *_), asynchronous(app):
            app.initialize_quote_state()
            wait_for(lambda: not app._io_starting, app._poll_io)
            self.assertTrue(app._storage_valid)
            self.assertTrue(app.active_price_config)

    def test_broken_shared_directory_is_visible_failure_not_zero_total(self):
        with application("manager") as (app, folder, *_), asynchronous(app):
            app.excel_total_income.set("上次有效金额")
            (folder / "storage.json").write_text('bad', encoding="utf-8")
            task = app.aggregate_all_excels(silent=True)
            wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
            self.assertIn("未确认", app.feedback)
            self.assertEqual(app.excel_total_income.get(), "上次有效金额")
            self.assertFalse(app._storage_valid)

    def test_background_json_save_retains_directory_and_exact_prices(self):
        with application("manager") as (app, folder, *_), asynchronous(app):
            storage = (folder / "storage.json").read_bytes()
            app.setting_rows[0]["sale"].set("0.015")
            task = app.save_settings();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
            self.assertEqual((folder / "storage.json").read_bytes(), storage)
            self.assertEqual(app.active_price_config.prices.items[0].sale, "0.015")

    def test_close_read_window_is_immediate_and_late_worker_never_updates_ui(self):
        with application("manager") as (app, *_):
            export_one(app)
            with asynchronous(app):
                started, release = Event(), Event()
                app.root.destroy = Mock()
                original = file_version
                def slow(path):started.set();release.wait(2);return original(path)
                try:
                    with patch("quote_files.cache.file_version", side_effect=slow):
                        app.refresh_excel_files();self.assertTrue(started.wait(1))
                        app.on_close()
                        app.root.destroy.assert_called_once()
                        release.set()
                    self.assertEqual(app.excel_file_tree.rows, {})
                finally:release.set()

    def test_close_write_keeps_window_alive_until_commit_state_delivered(self):
        with application("manager") as (app, *_), asynchronous(app):
            import quote_app.integration as integration
            started, release = Event(), Event()
            app.root.destroy = Mock()
            app.setting_rows[0]["sale"].set("0.025")
            original = integration.save_config
            def slow(*args, **kwargs):started.set();release.wait(2);return original(*args, **kwargs)
            try:
                with patch.object(integration, "save_config", side_effect=slow):
                    task = app.save_settings();self.assertTrue(started.wait(1))
                    app.on_close();app.root.destroy.assert_not_called()
                    self.assertIn("等待原写任务", app.background_status_var.get())
                    release.set();wait_for(lambda: app.root.destroy.called, app._poll_io)
                self.assertIsNotNone(app.last_file_transaction)
                self.assertEqual(app.active_price_config.prices.items[0].sale, "0.025")
                self.assertNotIn(task.number, app._io_callbacks)
            finally:release.set()

    def test_unknown_excel_result_queries_original_request_then_replays_without_duplicate(self):
        with application("manager") as (app, *_):
            path = export_one(app);app.calculate(notify=False)
            with asynchronous(app):
                from quote_files import transactions as tx
                original = tx.read_bytes
                count = 0
                def lose(target):
                    nonlocal count
                    if Path(target) == path:
                        count += 1
                        if count >= 3:raise OSError("synthetic readback unavailable")
                    return original(target)
                with patch.object(tx, "read_bytes", side_effect=lose):
                    task = app.export_to_excel();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                self.assertTrue(app._excel_pending["unknown"])
                rid = app._excel_pending["request"].request_id
                self.assertIn(rid, app.feedback)
                query = app.check_last_write();wait_for(lambda: query.number not in app._io_callbacks, app._poll_io)
                self.assertFalse(app._excel_pending["unknown"])
                retry = app.export_to_excel();wait_for(lambda: retry.number not in app._io_callbacks, app._poll_io)
                self.assertEqual(app.last_file_transaction.request_id, rid)
                self.assertTrue(app.last_file_transaction.already_committed)
                self.assertEqual(read_ledger(path).totals.income_cents, 2400)

    def test_failed_note_task_preserves_editor_until_original_request_succeeds(self):
        with application("manager") as (app, *_):
            from test_order_management import display
            from quote_files.transactions import FileBusy
            path = export_one(app)
            display(app, path)
            app.excel_remark_text.insert("1.0", "失败后保留本条")
            with asynchronous(app):
                app.excel_sheet_var.set("利润明细")
                with patch("quote_app.file_edits.workbook_transaction", side_effect=FileBusy("synthetic occupied file")):
                    task = app.save_current_excel_remark();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                self.assertEqual(app.excel_remark_text.text, "失败后保留本条")
                rid = app._edit_pending["request"].request_id
                retry = app.save_current_excel_remark();wait_for(lambda: retry.number not in app._io_callbacks, app._poll_io)
                self.assertEqual(app.last_file_transaction.request_id, rid)
                self.assertEqual(app.excel_remark_text.text, "")

    def test_windows_gui_entry_is_blocked_elsewhere_without_constructing_any_window(self):
        import p04_io_check as check
        with patch.object(check, "run_checks", return_value={"status":"passed"}), patch.object(check.platform,"system",return_value="Linux"), patch.object(check,"run_gui") as gui, patch("baseline_check.emit"):
            self.assertEqual(check.main(["--gui-smoke"]), 2)
            gui.assert_not_called()

    def test_directory_editor_changed_during_observation_is_not_overwritten(self):
        with application("manager") as (app, *_), asynchronous(app):
            started, release = Event(), Event()
            original = app.__class__._read_price_candidate
            def slow(worker):started.set();release.wait(2);return original(worker)
            try:
                with patch.object(app.__class__,"_read_price_candidate",slow):
                    task=app.reload_price_settings_from_json(silent=True);self.assertTrue(started.wait(1))
                    app.export_dir_var.set("未保存的新目录草稿")
                    release.set();wait_for(lambda: task.number not in app._io_callbacks, app._poll_io)
                self.assertEqual(app.export_dir_var.get(),"未保存的新目录草稿")
            finally:release.set()


if __name__ == "__main__":unittest.main()
