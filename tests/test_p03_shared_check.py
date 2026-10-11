"""Auxiliary shared diagnostic boundaries; no claim of physical Windows/SMB runs."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import p03_shared_check as check
from test_application_integration import application
from test_workbook_transactions import bind_view
from quote_files.transactions import FileBusy, file_lock
from quote_files.transactions import FileFailure
from quote_files.workbooks import open_book


@contextmanager
def shared_app(role, sandbox):
    with application(role) as (app, _, namespace, _):
        namespace.update(LAN_PRICE_CONFIG_FILE=str(sandbox / "config.json"),
                         LAN_DATA_DIR=str(sandbox / "reports"), LAN_SCREENSHOT_DIR=str(sandbox / "screenshots"))
        app.data_source_var.set(str(sandbox))
        assert app.apply_connection(), app.feedback
        app.reload_price_settings_from_json(silent=True)
        events = []
        app.__class__ = check.observed_type(type(app), events)
        app.add_fixture_row(product="共享测试商品")
        yield app, events


def export(app, reference):
    app.order_no.set(reference)
    app.calculate(notify=False)
    app.confirm_current_prices()
    path = app.export_to_excel()
    if not path:
        raise AssertionError(app.feedback)
    return Path(path)


class SharedDiagnosticTests(unittest.TestCase):
    def test_prepare_unique_child_and_reject_unmarked_or_missing_config_without_repair(self):
        with tempfile.TemporaryDirectory() as parent:
            parent = Path(parent)
            production = parent / "config.json"
            production.write_bytes(b"production sentinel")
            with self.assertRaises(FileNotFoundError):
                check.validate(parent)
            first, second = check.prepare(parent), check.prepare(parent)
            self.assertNotEqual(first, second)
            self.assertEqual(check.validate(first)[0], first)
            (first / "config.json").unlink()
            with self.assertRaises(ValueError):
                check.validate(first)
            self.assertFalse((first / "config.json").exists())
            self.assertEqual(production.read_bytes(), b"production sentinel")

    def test_code_mismatch_and_output_directory_link_are_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            sandbox = check.prepare(Path(parent))
            marker = sandbox / "p03-test.json"
            raw = marker.read_bytes()
            data = json.loads(raw)
            data["implementation_sha256_LF"] = {}
            marker.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "指纹"):
                check.validate(sandbox)
            marker.write_bytes(raw)
            (sandbox / "reports").rmdir()
            try:
                (sandbox / "reports").symlink_to(Path(parent), target_is_directory=True)
            except OSError:
                self.skipTest("host does not permit creating directory links")
            with self.assertRaisesRegex(ValueError, "链接"):
                check.validate(sandbox)

    def test_two_current_adapters_share_fixture_replay_then_void_and_readonly_reconcile(self):
        with tempfile.TemporaryDirectory() as parent:
            sandbox = check.prepare(Path(parent))
            with shared_app("manager", sandbox) as (manager, a_events), shared_app("sales", sandbox) as (sales, b_events):
                path = export(manager, "A01")
                self.assertEqual(export(sales, "B01"), path)
                self.assertEqual(Path(sales.export_to_excel()), path)
                self.assertTrue(b_events[-1]["already_committed"])
                before = check.gui.files(sandbox)
                result = check.verify(sandbox, 2)
                self.assertEqual(result["counts"]["append_receipts"], 2)
                self.assertEqual(result["files"][0]["summary"], ("20.00", "8.00", "12.00"))
                self.assertEqual(check.gui.files(sandbox), before)
                with self.assertRaisesRegex(ValueError, "订单数"):
                    check.verify(sandbox, 3)
                bind_view(manager, path)
                manager._edit_order("append_remark", "共享测试备注")
                bind_view(manager, path)
                manager._edit_order("void_order")
                result = check.verify(sandbox, 2, 1)
                self.assertEqual(result["files"][0]["summary"], ("10.00", "4.00", "6.00"))
                self.assertEqual([e["operation"] for e in a_events], ["append_quote", "append_remark", "void_order"])
                self.assertTrue(all(e["status"] == "committed" for e in a_events))

    def test_held_lock_blocks_current_writer_then_same_request_retries_once(self):
        with tempfile.TemporaryDirectory() as parent:
            sandbox = check.prepare(Path(parent))
            with shared_app("manager", sandbox) as (manager, events):
                path = export(manager, "A01")
                manager.order_no.set("A02")
                manager.calculate(notify=False)
                before = path.read_bytes()
                with file_lock(path):
                    self.assertFalse(manager.export_to_excel())
                    self.assertEqual(events[-1]["status"], "unconfirmed")
                    rid = events[-1]["request_id"]
                    self.assertIsNotNone(rid)
                    self.assertEqual(path.read_bytes(), before)
                self.assertEqual(Path(manager.export_to_excel()), path)
                self.assertEqual(events[-1]["request_id"], rid)
                check.verify(sandbox, 2)
                def check_locked(_):
                    with self.assertRaises(FileBusy):
                        with file_lock(path):
                            self.fail("second writer acquired held lock")
                with patch.object(check.time, "sleep", side_effect=check_locked):
                    held = check.hold(sandbox, 10)
                self.assertEqual(held["before_sha256"], held["while_locked_sha256"])
                self.assertTrue(held["lock_released"])

    def test_verify_detects_corrupt_summary_and_duplicate_human_order_reference(self):
        with tempfile.TemporaryDirectory() as parent:
            sandbox = check.prepare(Path(parent))
            with shared_app("manager", sandbox) as (app, _):
                path = export(app, "A01")
                before = path.read_bytes()
                book = open_book(before)
                try:
                    book["利润明细"].cell(4, 2, "0.00")
                    book.save(path)
                finally:
                    book.close()
                with self.assertRaisesRegex(FileFailure, "摘要"):
                    check.verify(sandbox, 1)
                path.write_bytes(before)
                export(app, "A01")  # A new calculation really is another order.
                with self.assertRaisesRegex(ValueError, "重复"):
                    check.verify(sandbox, 2)

    def test_cli_nonwindows_and_unmarked_unc_do_not_launch_or_create_files(self):
        with patch.object(check.platform, "system", return_value="Linux"), patch.object(check.baseline_check, "emit") as emit, patch.object(check, "prepare", side_effect=AssertionError("created")):
            self.assertEqual(check.main(["--prepare", r"\\server\share"]), 2)
            self.assertEqual(emit.call_args.args[0]["status"], "blocked")
        with patch.object(check.platform, "system", return_value="Windows"), patch.object(check.baseline_check, "emit") as emit, patch.object(check, "launch", side_effect=AssertionError("launched")):
            self.assertEqual(check.main(["--launch", "manager", "--sandbox", "E:/production"]), 1)
            self.assertIn("UNC", emit.call_args.args[0]["error"])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "previous.json"
            output.write_bytes(b"previous report")
            with patch.object(check.sys, "stderr"), patch.object(check, "prepare", side_effect=AssertionError("created")):
                with self.assertRaises(SystemExit):
                    check.main(["--prepare", r"\\server\share", "--output", str(output)])
            self.assertEqual(output.read_bytes(), b"previous report")


if __name__ == "__main__":
    unittest.main()
