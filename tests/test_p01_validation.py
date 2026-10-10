"""Meaningful checks for P01 assets and diagnostic isolation, not app acceptance."""
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import p01_fixtures as fixtures
import p01_oracle as oracle
import p01_validation as validation


class P01ValidationTests(unittest.TestCase):
    def test_static_amounts_and_rejection_targets(self):
        suite = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))
        self.assertEqual(len(suite["cases"]), suite["case_count"])
        self.assertEqual(len({case["id"] for case in suite["cases"]}), suite["case_count"])
        for case in suite["cases"]:
            with self.subTest(case=case["id"]):
                observed = oracle.quote(case)
                self.assertEqual({key: observed[key] for key in case["expected"]}, case["expected"])
                if observed["status"] == "ok":
                    for field in ("income", "cost", "profit"):
                        self.assertEqual(sum(oracle.Fraction(line[field]) for line in observed["lines"]), oracle.Fraction(observed["totals"][field]))

    def test_negative_tie_and_no_float_loss(self):
        self.assertEqual(oracle.half_up(oracle.Fraction("-0.005"), 2), -1)
        self.assertEqual(oracle.half_up(oracle.Fraction("0.005"), 2), 1)
        self.assertEqual(oracle.half_up(oracle.Fraction("92233720368547758.07"), 2), 9223372036854775807)

    def test_division_order_and_original_remainder_semantics(self):
        self.assertEqual(oracle.number("1/3*3"), oracle.Fraction("0.999999999999"))
        self.assertEqual(oracle.number("(0-5)%3"), 1)
        self.assertEqual(oracle.number("(5)%(0-3)+3"), 2)
        self.assertEqual(oracle.number("0.0050000000000"), oracle.Fraction("0.005"))

    def test_bounded_text_ast_intermediate_and_literals(self):
        for raw in (" " * 257, "1+" * 41 + "1", "-" * 18 + "1", "1e999999999", "0.0000000000001", "1000000000*1000000000*1000000000*1000000000*1000000000*1000000000"):
            with self.subTest(raw=raw), self.assertRaises(oracle.Validation):
                oracle.number(raw)

    def test_order_line_limit_blocks_whole_order(self):
        suite = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))
        case = suite["cases"][0].copy()
        case["input"] = case["input"] * 10001
        result = oracle.quote(case)
        self.assertEqual(result["status"], "VALIDATION")
        self.assertIsNone(result["totals"])

    def test_expected_mutation_is_detectable(self):
        suite = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))
        case = next(case for case in suite["cases"] if case["id"] == "E03")
        observed = oracle.quote(case)
        changed = json.loads(json.dumps(case["expected"]))
        changed["totals"]["income"] = "0.01"
        self.assertNotEqual(observed, changed)

    def test_output_cannot_overwrite_or_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "reports").mkdir()
            output = validation.new_output(root / "reports/run", root)
            with self.assertRaises(FileExistsError):
                validation.new_output(output, root)
            for path in (root / "source", root / "reports"):
                with self.assertRaises(ValueError):
                    validation.new_output(path, root)

    def test_output_symlink_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "reports").mkdir()
            link = root / "reports/link"
            try:
                link.symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable in this test environment")
            with self.assertRaises(ValueError):
                validation.new_output(link / "run", root)

    def test_baseline_change_blocks_diagnostic_execution(self):
        with patch.object(validation.baseline_check, "inspect_source", return_value={"status": "changed"}):
            with self.assertRaisesRegex(ValueError, "SOURCE_BASELINE_CHANGED"):
                validation.gate()

    def test_format_candidates_preserve_same_second_and_cache_states(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "formats"
            entries = fixtures.formats(folder)
            results = validation.check_formats(folder, entries)
            self.assertTrue(all(result["passed"] and result["source_unchanged"] for result in results))
            wb = fixtures.openpyxl.load_workbook(folder / "ledger_current.xlsx", read_only=True)
            try:
                rows = list(wb.active.iter_rows(min_row=7, values_only=True))
                self.assertEqual(rows[0][0], rows[1][0])
                self.assertNotEqual(rows[0][2], rows[1][2])
            finally:
                wb.close()

    def test_instrumentation_restores_library_on_failure(self):
        namespace = {"PriceCalculator": type("Stub", (), {"refresh_excel_files": lambda self: None})}
        namespace["PriceCalculator"].refresh_excel_files.__globals__["load_workbook"] = fixtures.openpyxl.load_workbook
        previous = validation.ReadOnlyWorksheet._get_source
        with self.assertRaises(RuntimeError):
            with validation.instrumentation(namespace):
                raise RuntimeError("synthetic failure")
        self.assertIs(validation.ReadOnlyWorksheet._get_source, previous)
        self.assertIs(namespace["PriceCalculator"].refresh_excel_files.__globals__["load_workbook"], fixtures.openpyxl.load_workbook)

    def test_scale_check_detects_missing_rows_and_changed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            fixtures.workbook(folder / "rows.xlsx", 2)
            fixtures.workbook(folder / "file_template.xlsx", 1)
            (folder / "files").mkdir()
            (folder / "files/bad.xlsx").write_bytes(b"changed synthetic bytes")
            manifest = {"row_sets": [{"path": "rows.xlsx", "detail_rows": 3, "income": "30", "cost": "12", "profit": "18"}], "file_sets": [{"path": "files", "files": 1}]}
            self.assertTrue(all(not check["passed"] for check in fixtures.check_scales(folder, manifest)))

    def test_timeout_records_failure_and_parent_cleans_only_gui_sandboxes(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for name in ("gui-manager-owned", "gui-sales-owned", "keep"):
                (output / name).mkdir()
            with patch.object(validation.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 30)) as run:
                results = validation.benchmarks(output, gui=True)
            self.assertEqual([result["status"] for result in results], ["timeout", "timeout"])
            self.assertEqual(run.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")
            self.assertTrue((output / "keep").is_dir())
            self.assertFalse(list(output.glob("gui-*-owned")))


if __name__ == "__main__":
    unittest.main()
