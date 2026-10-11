"""P03-04 order management checks, synthetic local files and optional Windows Tk."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tests")]
from p03_format_check import case_ids
import p02_gui_check as gui
BASE_SHARED_SMOKE = gui.shared_directory_smoke


def order_gui_smoke(manager, sales, sandbox):
    from quote_files.reading import read_ledger
    checks = BASE_SHARED_SMOKE(manager, sales, sandbox)
    for app in (manager, sales):
        for job in tuple(app._after_jobs):
            app.root.after_cancel(job)
        app._after_jobs.clear()
    path = Path(sales.get_daily_excel_path())
    manager.add_calc_row("第二个订单", "P02面积", False)
    manager.user_name.set(sales.user_name.get())
    manager.calculate(notify=False)
    manager.confirm_current_prices()
    assert manager.export_to_excel() == str(path)
    manager.open_excel_path(str(path))
    manager.excel_view_tree.selection_set("row_7")
    first = manager.load_current_excel_remark()
    assert first and first.state == "active"
    manager.excel_remark_text.insert("1.0", "=第一单备注")
    manager.excel_note_button.invoke()
    first = manager.load_current_excel_remark()
    assert first.notes[0][1] == "=第一单备注"
    assert manager.excel_order_history.cget("state") == "disabled"
    manager.excel_view_tree.selection_set("row_9")
    second = manager.load_current_excel_remark()
    assert second.order_id != first.order_id and not second.notes
    assert "=第一单备注" not in manager.excel_order_history.get("1.0", "end")
    manager.excel_remark_text.insert("1.0", "第二单草稿")
    manager.excel_view_tree.selection_set("row_7")
    manager.load_current_excel_remark()
    assert "=第一单备注" in manager.excel_order_history.get("1.0", "end")
    manager.excel_order_reason.set("合成取消原因")
    before = path.read_bytes()
    with patch("tkinter.messagebox.askyesno", return_value=False):
        manager.excel_void_button.invoke()
    assert path.read_bytes() == before
    with patch("tkinter.messagebox.askyesno", return_value=True):
        manager.excel_void_button.invoke()
    void = manager.load_current_excel_remark()
    assert void.state == "void" and void.notes == first.notes
    assert str(manager.excel_note_button.cget("state")) == "disabled"
    assert str(manager.excel_restore_button.cget("state")) == "normal"
    assert read_ledger(path).totals.income_cents == 1200
    sales.open_excel_path(str(path))
    assert len(sales.excel_view_tree.get_children()) == 1
    manager.excel_order_reason.set("合成核对恢复")
    with patch("tkinter.messagebox.askyesno", return_value=True):
        manager.excel_restore_button.invoke()
    restored = manager.load_current_excel_remark()
    assert restored.state == "active" and restored.notes == first.notes
    assert restored.prices == first.prices and restored.inputs == first.inputs
    assert read_ledger(path).totals.income_cents == 2400
    assert [e[1] for e in restored.events] == ["append_quote", "append_remark", "void_order", "restore_order"]
    sales.load_current_excel_sheet()
    assert len(sales.excel_view_tree.get_children()) == 2
    manager.excel_view_tree.selection_set("row_9")
    manager.load_current_excel_remark()
    assert manager.excel_remark_text.get("1.0", "end").strip() == "第二单草稿"
    checks.update(order_specific_readonly_history="passed", order_drafts_do_not_cross="passed",
                  cancel_zero_writes="passed", actual_void_restore_buttons_and_reason="passed",
                  restore_amount_once_notes_prices_inputs_preserved="passed", sales_void_hidden_restore_visible="passed")
    for app in (manager, sales):
        app.schedule_quote_callback(lambda: (_ for _ in ()).throw(AssertionError("closed callback ran")), delay=1)
    return checks


def run_checks():
    suite = unittest.defaultTestLoader.loadTestsFromName("test_order_management")
    ids = list(case_ids(suite))
    log, start = io.StringIO(), time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    return {"status": "passed" if result.wasSuccessful() else "failed", "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "skipped": result.skipped,
            "elapsed_seconds": round(time.monotonic() - start, 3), "test_ids": ids, "log": log.getvalue()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui-smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    paths = sorted([*ROOT.glob("quote_files/*.py"), *ROOT.glob("quote_app/*.py"), *ROOT.glob("报价*.py"),
                    ROOT / "tests/test_order_management.py", ROOT / "tools/p02_gui_check.py", Path(__file__)])
    checks = run_checks()
    report = {"task": "P03-04", "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "environment": {"os": platform.system(), "python": platform.python_version()},
              "implementation_sha256_LF": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths},
              "scope": "Synthetic temporary local orders and optional actual Windows Tk; no production files or physical screen capture",
              "production_paths_accessed": False, "windows_gui": "not_requested", "checks": checks, "status": checks["status"]}
    if args.gui_smoke:
        if platform.system() != "Windows":
            report["windows_gui"] = "blocked: Windows GUI only"
            report["status"] = "blocked" if checks["status"] == "passed" else "failed"
        elif checks["status"] == "passed":
            try:
                with patch.object(gui, "shared_directory_smoke", side_effect=order_gui_smoke):
                    report["windows_gui"] = gui.run_pair()
                report["status"] = report["windows_gui"]["status"]
            except Exception as exc:
                report["windows_gui"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                report["status"] = "failed"
    from baseline_check import emit
    emit(report, args.output)
    return 2 if report["status"] == "blocked" else int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
