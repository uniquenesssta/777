"""P04-01 temporary background I/O checks and actual Windows event-loop checks."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tests")]
import p02_gui_check as gui
from p03_format_check import case_ids


def run_checks():
    suite = unittest.defaultTestLoader.loadTestsFromName("test_background_io")
    ids = list(case_ids(suite));log = io.StringIO();start = time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    return {"status": "passed" if result.wasSuccessful() else "failed", "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": result.skipped,
        "elapsed_seconds": round(time.monotonic() - start, 3), "test_ids": ids, "log": log.getvalue()}


def run_gui():
    import tkinter as tk
    from quote_files.reading import read_ledger
    import quote_app.integration as integration
    report = {"status": "running", "scope": "Actual Windows Tk, synthetic temporary local files and deliberately delayed I/O; no production share or screen capture", "checks": {}}
    with tempfile.TemporaryDirectory(prefix="777-p04-io-") as folder:
        sandbox = Path(folder);owner = tk.Tk();owner.withdraw()
        errors = gui.track_callback_errors(owner)
        apps, releases = [], []
        active_patches = []
        ticks = []
        def heartbeat():
            ticks.append(time.monotonic())
            if report["status"] == "running":owner.after(20, heartbeat)
        try:
            for role in ("manager", "sales"):
                ns, _ = gui.load_namespace(ROOT, role, sandbox)
                class Live(gui.live_sandbox_type(ns, sandbox)):
                    background_io_enabled = True
                app = Live(tk.Toplevel(owner));apps.append(app)
            manager, sales = apps
            def await_task(task):
                assert task and hasattr(task, "number"), "request was not queued"
                yield lambda: task.number not in manager._io_callbacks and task.number not in sales._io_callbacks
            def window_exists(app):
                try:return bool(app.root.winfo_exists())
                except tk.TclError:return False
            def steps():
                yield lambda: all(a._storage_valid and a.active_price_config and not a._io_starting for a in apps)
                report["checks"]["async_startup_restores_role_connections"] = "passed"
                for app in apps:
                    app.add_calc_row("后台测试订单", "P02面积", False)
                    app.user_name.set("P04背景测试")
                    yield from await_task(app.calculate(notify=False))
                    assert app.summary_income.get() == "12.00"
                    yield from await_task(app.confirm_current_prices())
                    app.calc_export_button.invoke()
                    yield from await_task(app._io_runtime.latest["write"])
                path = Path(sales.last_file_transaction.path)
                assert read_ledger(path).totals.income_cents == 2400
                report["checks"]["async_calculate_confirm_real_export_buttons"] = "passed"
                yield from await_task(manager.open_excel_path(str(path)))
                manager.excel_view_tree.selection_set("row_7");manager.load_current_excel_remark()
                manager.excel_remark_text.insert("1.0", "后台追加备注")
                manager.excel_note_button.invoke();yield from await_task(manager._io_runtime.latest["write"])
                yield lambda: bool(manager._excel_view_orders) and not manager._io_callbacks
                manager.excel_view_tree.selection_set("row_7");manager.load_current_excel_remark()
                assert "后台追加备注" in manager.excel_order_history.get("1.0", "end")
                manager.excel_order_reason.set("后台作废测试")
                manager.excel_void_button.invoke();yield from await_task(manager._io_runtime.latest["write"])
                yield lambda: bool(manager._excel_view_orders) and not manager._io_callbacks
                manager.excel_order_reason.set("后台恢复测试")
                manager.excel_restore_button.invoke();yield from await_task(manager._io_runtime.latest["write"])
                yield lambda: bool(manager._excel_view_orders) and not manager._io_callbacks
                assert read_ledger(path).totals.income_cents == 2400
                report["checks"]["async_order_note_void_restore_preserves_money"] = "passed"
                yield from await_task(sales.open_excel_path(str(path)))
                assert len(sales.excel_view_tree.get_children()) == 2
                report["checks"]["async_sales_view_is_correct"] = "passed"
                started, release = Event(), Event();releases.append(release)
                original = read_ledger
                def slow_read(path):started.set();release.wait(5);return original(path)
                delayed = patch("quote_files.reading.read_ledger", side_effect=slow_read);delayed.start();active_patches.append(delayed)
                task = manager.refresh_excel_files();yield started.is_set
                prior_ticks = len(ticks)
                manager.user_name.set("慢扫描期间编辑成功")
                yield lambda: len(ticks) >= prior_ticks + 3
                assert manager.user_name.get() == "慢扫描期间编辑成功" and task.state == "running"
                manager.cancel_background_reads();release.set()
                yield lambda: task.state == "cancelled"
                delayed.stop();active_patches.remove(delayed)
                report["checks"]["slow_scan_owner_editing_heartbeat_and_cancel"] = "passed"
                started, release = Event(), Event();releases.append(release)
                delayed = patch("quote_files.reading.read_ledger", side_effect=slow_read);delayed.start();active_patches.append(delayed)
                task = manager.refresh_excel_files();yield started.is_set
                manager.on_close();assert not window_exists(manager)
                release.set();yield lambda: task.state == "cancelled"
                delayed.stop();active_patches.remove(delayed)
                report["checks"]["close_read_window_while_io_is_running"] = "passed"
                sales.order_no.set("关闭中提交状态测试")
                yield from await_task(sales.calculate(notify=False))
                yield from await_task(sales.confirm_current_prices())
                started, release = Event(), Event();releases.append(release)
                original_transaction = integration.workbook_transaction
                def slow_write(*args, **kwargs):started.set();release.wait(5);return original_transaction(*args, **kwargs)
                delayed = patch.object(integration, "workbook_transaction", side_effect=slow_write);delayed.start();active_patches.append(delayed)
                task = sales.export_to_excel();yield started.is_set
                sales.on_close();assert window_exists(sales)
                prior_ticks = len(ticks);yield lambda: len(ticks) >= prior_ticks + 3
                assert window_exists(sales)
                release.set();yield lambda: not window_exists(sales)
                delayed.stop();active_patches.remove(delayed)
                assert sales.last_file_transaction and read_ledger(path).totals.income_cents == 3600
                report["checks"]["close_write_waits_for_receipt_with_live_event_loop"] = "passed"
            sequence = steps();waiting = None;deadline = time.monotonic() + 30
            def drive():
                nonlocal waiting, deadline
                try:
                    if time.monotonic() > deadline:raise TimeoutError("GUI diagnostic step did not complete")
                    if waiting is None or waiting():
                        waiting = next(sequence);deadline = time.monotonic() + 30
                    owner.after(10, drive)
                except StopIteration:
                    report["status"] = "passed";owner.quit()
                except Exception as exc:
                    report.update(status="failed", error=f"{type(exc).__name__}: {exc}");owner.quit()
            owner.after(10, heartbeat);owner.after(10, drive)
            with patch("tkinter.messagebox.showinfo"), patch("tkinter.messagebox.showwarning"), patch("tkinter.messagebox.showerror"), patch("tkinter.messagebox.askyesno", return_value=True):
                owner.mainloop()
        finally:
            for release in releases:release.set()
            for item in active_patches:item.stop()
            for app in apps:
                if app._io_runtime.writing:
                    # Continue the event loop until the original write reports;
                    # a diagnostic timeout never authorizes killing a commit.
                    while app._io_runtime.writing:
                        owner.update();time.sleep(.01)
                if not app._io_runtime.writing:
                    try:app.on_close()
                    except tk.TclError:pass
            report["callback_errors"] = errors
            report["heartbeat_samples"] = len(ticks)
            report["max_heartbeat_gap_ms"] = round(max((b-a)*1000 for a,b in zip(ticks,ticks[1:])), 3) if len(ticks)>1 else None
            report["heartbeat_scope"] = "Short deliberately blocked-I/O diagnostic; not P04-04 production performance acceptance"
            owner.destroy()
            if errors:report["status"] = "failed"
    report.update(close="ok", sandbox_cleaned=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui-smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    checks = run_checks()
    paths = sorted([*ROOT.glob("quote_app/*.py"), *ROOT.glob("quote_files/*.py"), *ROOT.glob("报价*.py"),
                    ROOT/'tests/test_background_io.py', ROOT/'tools/p02_gui_check.py', Path(__file__)])
    report = {"task": "P04-01", "commit": subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        "environment": {"os":platform.system(),"python":platform.python_version()}, "checks":checks,
        "implementation_sha256_LF":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths},
        "production_paths_accessed":False,"scope":"Temporary synthetic files, bounded background jobs and optional actual Windows Tk","windows_gui":"not_requested","status":checks["status"]}
    if args.gui_smoke:
        if platform.system()!='Windows':report.update(status='blocked' if checks['status']=='passed' else 'failed',windows_gui='blocked: Windows GUI only')
        elif checks['status']=='passed':
            try:report['windows_gui']=run_gui();report['status']=report['windows_gui']['status']
            except Exception as exc:report.update(status='failed',windows_gui={'status':'failed','error':f'{type(exc).__name__}: {exc}'})
    from baseline_check import emit
    emit(report,args.output)
    return 2 if report['status']=='blocked' else int(report['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
