"""P01-03 collector safety/schema checks; synthetic files, no Windows/SMB claim."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect_p01_samples", ROOT / "tools/collect_p01_samples.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "reports" / "run1"
        # Exercise UTF-8 snapshots with a GBK text default on every host.
        # Explicit encodings and binary I/O retain their normal behavior.
        default_codec = patch("io.text_encoding", side_effect=lambda encoding, stacklevel=2:
                              "gbk" if encoding in (None, "locale") else encoding)
        default_codec.start()
        self.addCleanup(default_codec.stop)

    def tearDown(self):
        # Windows requires removing the readonly attribute before cleanup.
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.temp.cleanup()

    def config(self, obj, name="source.json"):
        path = self.root / name
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return path

    def workbook(self, headers=None, row=None, sheet="利润明细"):
        path = self.root / "source.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet
        ws.append(headers or tool.HEADERS)
        if row is not None:
            ws.append(row)
        wb.save(path)
        wb.close()
        return path

    def read_public(self):
        return json.loads((self.output / "public/S001.json").read_text(encoding="utf-8"))

    def test_original_preserved_and_snapshot_readonly(self):
        path = self.config({"items": [{"name": "秘密商品", "sale": "12.5", "cost": "4", "k": "", "single": True}]})
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns
        report = tool.collect([("manager", "config", path)], self.output, self.root)
        self.assertEqual(report["files"][0]["source_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual((self.output / "private/S001.json").read_bytes(), before)
        self.assertFalse((self.output / "private/S001.json").stat().st_mode & stat.S_IWUSR)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(self.read_public()["items"][0]["k"], "")

    def test_config_shape_types_and_unknown_values_are_redacted(self):
        path = self.config({"export_dir": "Z:\\私密路径", "secret": "客户私密", "items": [{"name": "商品私密", "sale": "1+2", "cost": "4元", "k": "1", "single": "false", "extra": "手机号私密"}]})
        tool.collect([("manager", "config", path)], self.output, self.root)
        public = self.read_public()
        self.assertIn("SINGLE_NOT_BOOLEAN", public["issues"])
        self.assertEqual(public["items"][0]["single"], "false")
        text = (self.output / "public/S001.json").read_text(encoding="utf-8")
        for secret in ("私密路径", "客户私密", "商品私密", "手机号私密"):
            self.assertNotIn(secret, text)
        self.assertEqual(public["unknown_top_field_count"], 1)

    def test_legacy_json_and_normalized_duplicate_names(self):
        old = tool.inspect_config(json.dumps({"私密名": ["12", "4", "1"], "export_dir": "秘密"}).encode(), tool.Redactor())
        self.assertEqual(old["schema"], "json_legacy_price_dict")
        new = tool.inspect_config(json.dumps({"items": [{"name": "A", "sale": "1", "cost": "0", "k": "1"}, {"name": " A ", "sale": "1", "cost": "0", "k": "1"}]}).encode(), tool.Redactor())
        self.assertIn("DUPLICATE_PRODUCT_NAME", new["issues"])

    def test_config_byte_comparison_is_not_physical_mapping_claim(self):
        first = self.config({"items": []}, "one.json")
        second = self.config({"items": []}, "two.json")
        report = tool.collect([("manager", "config", first), ("sales", "config", second)], self.output, self.root)
        self.assertTrue(report["manager_sales_config_bytes_equal"])
        self.assertTrue(report["same_bytes_do_not_prove_same_physical_share"])

    def test_current_excel_customer_order_and_formula_never_leak(self):
        row = [None] * len(tool.HEADERS)
        for field, value in {"记录时间": "2026-10-10 12:00:00", "淘宝ID": "00123-秘密客户", "订单号": "私密订单", "微信号": "秘密微信", "项目名称": "秘密商品", "数量": "2", "销售额": "=HYPERLINK(\"https://secret.invalid\",\"机密\")"}.items():
            row[tool.HEADERS.index(field)] = value
        path = self.workbook(row=row)
        before = path.read_bytes()
        tool.collect([("unspecified", "excel", path)], self.output, self.root)
        public = self.read_public()["sheets"][0]
        self.assertEqual(public["schema"], "excel_current_26")
        formula = next(c for c in public["cells"] if c["row"] == 2 and c["column"] == 17)
        self.assertTrue(formula["value"]["formula_redacted"])
        self.assertFalse(formula["value"]["has_cached_value"])
        self.assertEqual(public["sampled_formula_without_cache"], 1)
        text = (self.output / "public/S001.json").read_text(encoding="utf-8")
        for secret in ("00123", "秘密客户", "私密订单", "秘密微信", "秘密商品", "secret.invalid", "机密"):
            self.assertNotIn(secret, text)
        self.assertEqual(path.read_bytes(), before)

    def test_numeric_customer_and_free_note_remain_redacted(self):
        row = [None] * (len(tool.HEADERS) + 1)
        row[1], row[4], row[16], row[-1] = 13912345678, "商品", 25.5, "私密备注内容"
        path = self.workbook(headers=tool.HEADERS + ["备注"], row=row)
        report = tool.collect([("unspecified", "excel", path)], self.output, self.root)
        self.assertEqual(report["files"][0]["status"], "observed")
        sheet = self.read_public()["sheets"][0]
        cells = {cell["column"]: cell["value"] for cell in sheet["cells"] if cell["row"] == 2}
        self.assertTrue(cells[2].startswith("客户"))
        self.assertEqual(cells[17], 25.5)
        text = (self.output / "public/S001.json").read_text(encoding="utf-8")
        self.assertNotIn("13912345678", text)
        self.assertNotIn("私密备注内容", text)

    def test_product_token_shared_between_config_and_excel(self):
        config = self.config({"items": [{"name": "商品A", "sale": "10", "cost": "4", "k": "1"}]})
        row = [None] * len(tool.HEADERS)
        row[4] = "商品A"
        workbook = self.workbook(row=row)
        tool.collect([("manager", "config", config), ("unspecified", "excel", workbook)], self.output, self.root)
        name = self.read_public()["items"][0]["name"]
        sheet = json.loads((self.output / "public/S002.json").read_text(encoding="utf-8"))["sheets"][0]
        self.assertEqual(next(c["value"] for c in sheet["cells"] if c["row"] == 2 and c["column"] == 5), name)

    def test_unknown_sheet_has_metadata_only(self):
        path = self.workbook(headers=["秘密表头", 13912345678], row=["客户秘密", "私密备注"], sheet="秘密工作表")
        tool.collect([("unspecified", "excel", path)], self.output, self.root)
        sheet = self.read_public()["sheets"][0]
        self.assertEqual(sheet["schema"], "unknown_sheet")
        self.assertEqual(sheet["cells"], [])
        self.assertNotIn("秘密", (self.output / "public/S001.json").read_text(encoding="utf-8"))

    def test_reordered_added_remark_and_legacy_header_classification(self):
        cases = [(list(reversed(tool.HEADERS)), "excel_current_26_reordered"), (tool.HEADERS + ["备注"], "excel_current_26_with_remark"), (["记录时间", "用户", "项目名称", "销售额", "总成本", "利润"], "excel_legacy_user_header"), (tool.HEADERS + ["淘宝ID"], "unknown_duplicate_headers")]
        for headers, expected in cases:
            self.assertEqual(tool.classify_header([(1, headers)])[2], expected)

    def test_existing_output_or_outside_reports_is_rejected(self):
        self.output.mkdir(parents=True)
        marker = self.output / "keep"
        marker.write_text("unchanged", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "OUTPUT_ALREADY_EXISTS"):
            tool.collect([], self.output, self.root)
        with self.assertRaisesRegex(ValueError, "OUTPUT_MUST_BE_NEW_REPORTS_SUBDIRECTORY"):
            tool.collect([], self.root / "production", self.root)
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((self.root / "production").exists())

    def test_output_symlink_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / "reports").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Host cannot create symlinks; Windows junction acceptance remains pending")
        with self.assertRaisesRegex(ValueError, "OUTPUT_LINK_DISALLOWED"):
            tool.collect([], self.output, self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_json_error_report_does_not_expose_excerpt_or_path(self):
        path = self.root / "私密姓名.json"
        path.write_text('{"客户秘密": invalid}', encoding="utf-8")
        report = tool.collect([("manager", "config", path)], self.output, self.root)
        self.assertEqual(report["files"][0]["status"], "blocked")
        public = (self.output / "public/manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("私密", public)
        self.assertNotIn("客户秘密", public)
        self.assertFalse((self.output / "public/S001.json").exists())

    def test_duplicate_json_keys_and_nonfinite_constants_are_blocked(self):
        for data, code in [(b'{"items":[],"items":[]}', "JSON_DUPLICATE_KEY"), (b'{"items":[],"value":NaN}', "JSON_NON_FINITE")]:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                tool.inspect_config(data, tool.Redactor())

    def test_changed_source_blocks_release_of_snapshot(self):
        path = self.config({"items": []})
        original_open = Path.open
        reads = [0]
        def changed_open(p, *args, **kwargs):
            if p == path and args and args[0] == "rb":
                reads[0] += 1
                if reads[0] == 2:
                    return io.BytesIO(b'{"changed":true}')
            return original_open(p, *args, **kwargs)
        with patch.object(Path, "open", changed_open):
            report = tool.collect([("manager", "config", path)], self.output, self.root)
        self.assertEqual(report["files"][0]["error_code"], "SOURCE_CHANGED_DURING_COLLECTION")
        self.assertFalse((self.output / "public/S001.json").exists())

    def test_zip_capacity_is_checked_before_workbook_loader(self):
        path = self.workbook()
        with patch.object(tool, "MAX_ZIP_BYTES", 1), patch.object(tool.openpyxl, "load_workbook") as load:
            report = tool.collect([("unspecified", "excel", path)], self.output, self.root)
        self.assertEqual(report["files"][0]["error_code"], "ZIP_CAPACITY_EXCEEDED")
        load.assert_not_called()

    def test_cli_requires_explicit_file_selection(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            tool.main(["--output", str(self.output)])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
