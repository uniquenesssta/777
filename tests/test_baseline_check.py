"""Safety regressions for the P01-01 diagnostic tool, not product acceptance."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("baseline_check", ROOT / "tools/baseline_check.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class BaselineCheckTests(unittest.TestCase):
    def test_original_sources_match_manifest(self):
        manifest = json.loads(baseline.MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            with self.subTest(role=entry["role"]):
                self.assertEqual(baseline.inspect_source(ROOT, entry)["status"], "ok")

    def test_changed_source_is_rejected_before_execution(self):
        # Marker would be created if unverified code were executed.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / "executed"
            (root / "source.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
            )
            entry = {"role": "manager", "path": "source.py", "git_blob_sha1": "wrong", "sha256": "wrong"}
            with self.assertRaises(ValueError):
                baseline.sandbox_namespace(root, entry, root / "sandbox")
            self.assertFalse(marker.exists())
            self.assertFalse((root / "sandbox").exists())

    def test_sandbox_replaces_every_storage_constant_and_leaves_source_intact(self):
        manifest = json.loads(baseline.MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            original = (ROOT / entry["path"]).read_bytes()
            with tempfile.TemporaryDirectory() as folder:
                sandbox = Path(folder)
                namespace = baseline.sandbox_namespace(ROOT, entry, sandbox)
                keys = ("DEFAULT_REPORT_DIR", "DEFAULT_CONFIG_FILE", "DEFAULT_SCREENSHOT_DIR") if entry["role"] == "manager" else ("LAN_DATA_DIR", "LAN_PRICE_CONFIG_FILE", "LAN_SCREENSHOT_DIR")
                for key in keys:
                    self.assertTrue(Path(namespace[key]).is_relative_to(sandbox))
                globals_used = namespace["PriceCalculator"].__init__.__globals__
                self.assertIs(globals_used, namespace)
                self.assertEqual(json.loads((sandbox / "config.json").read_text(encoding="utf-8"))["items"][0]["sale"], "50")
            self.assertEqual((ROOT / entry["path"]).read_bytes(), original)

    def test_missing_dependency_is_actionable(self):
        entry = {"module": "openpyxl", "distribution": "openpyxl", "required_for": "Excel"}
        with patch.object(baseline.importlib, "import_module", side_effect=ImportError("missing package")):
            result = baseline.inspect_dependency(entry)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("ImportError", result["error"])

    def test_manual_file_choice_outside_sandbox_is_blocked_before_read(self):
        class Original:
            def open_excel_path(self, path):
                raise AssertionError("Must not reach actual workbook reader")
        with tempfile.TemporaryDirectory() as folder:
            sandbox = Path(folder) / "sandbox"
            app_type = baseline.sandbox_application_type({"PriceCalculator": Original}, sandbox)
            with self.assertRaises(ValueError):
                app_type().open_excel_path(Path(folder) / "actual-orders.xlsx")

    def test_gui_mode_blocks_non_windows_before_loading_applications(self):
        report = {"environment": {"target_windows": False}, "sources": [], "dependencies": []}
        with patch.object(baseline, "inspect_environment", return_value=report), patch.object(baseline, "run_gui") as gui, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(baseline.main(["--gui-smoke"]), 2)
        gui.assert_not_called()
        self.assertEqual(report["gui"]["status"], "blocked")

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            output.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                baseline.emit({"result": "new"}, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
