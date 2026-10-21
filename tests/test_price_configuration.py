"""P02-02 whole-config acceptance, compatibility and transition regressions."""

from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quote_core import (
    DiscountLine, NormalLine, PriceItem, PriceSnapshot, QuoteSnapshot,
    calculate_quote, capture_legacy_quote, parse_number, parse_percent,
    parse_price_config, refresh_price_config,
)
from quote_core import configuration as config_module


def document(*items, **metadata):
    return json.dumps(dict(metadata, items=list(items)), ensure_ascii=False)


def item(name="P", **fields):
    return dict(name=name, sale="50", cost="20", single=True, **fields)


class PriceConfigurationTests(unittest.TestCase):
    def parse(self, source, **kwargs):
        return parse_price_config(source, price_version_id="v1", **kwargs)

    def rejected(self, source, reason=None, field=None, **kwargs):
        result = self.parse(source, **kwargs)
        self.assertEqual(result.status, "VALIDATION")
        self.assertIsNone(result.config)
        self.assertTrue(result.issues)
        if reason is not None:
            self.assertIn(reason, [issue.reason for issue in result.issues])
        if field is not None:
            self.assertIn(field, [issue.field for issue in result.issues])
        return result

    def test_current_units_alias_and_export_metadata_feed_the_shared_core(self):
        raw = document({"name": "面积", "sale": "2+3元", "cost": "1", "k": "1.5倍", "qty_only": False},
                       {"name": "单件", "sale": "0.005", "cost": "0", "single": True},
                       export_dir=r"\\192.168.4.38\共享盘\利润表")
        with localcontext() as context:
            context.prec = 2
            parsed = self.parse(raw)
        self.assertEqual(parsed.status, "ok")
        config = parsed.config
        self.assertEqual(config.source_schema, "json_items")
        self.assertEqual(config.export_dir, r"\\192.168.4.38\共享盘\利润表")
        self.assertEqual(config.original_json, raw)
        result = calculate_quote(QuoteSnapshot("v1", (NormalLine("面积", "4", "2", "3"),
                                                       NormalLine("单件", "1"))), config.prices)
        self.assertEqual(result.totals.income_cents, 18001)
        self.assertEqual(result.totals.cost_cents, 2400)

    def test_legacy_requires_explicit_single_policy_and_keeps_metadata(self):
        raw = '{"架":[50,20,""],"板":["3.5",1,"1"],"export_dir":"E:\\\\利润表"}'
        self.rejected(raw, "LEGACY_SINGLE_POLICY_REQUIRED")
        parsed = self.parse(raw, legacy_single_names=("架",))
        self.assertEqual(parsed.status, "ok")
        self.assertEqual(parsed.config.source_schema, "json_legacy_price_dict")
        self.assertEqual([p.single for p in parsed.config.prices.items], [True, False])
        quote = QuoteSnapshot("v1", (NormalLine("架", "1"), NormalLine("板", "1", "2", "3")))
        self.assertEqual(calculate_quote(quote, parsed.config.prices).totals.income_cents, 7100)
        self.assertFalse(self.parse(raw, legacy_single_names=()).config.prices.items[0].single)

    def test_legacy_shape_and_malformed_current_items_never_fall_back(self):
        for values in ([1, 2], [1, 2, 3, 4], {}, None, False, "1"):
            with self.subTest(values=values):
                self.rejected(json.dumps({"P": values}), "LEGACY_PRICE_SHAPE", legacy_single_names=())
        for value in ({}, None, False, "bad"):
            with self.subTest(items=value):
                self.rejected(json.dumps({"items": value, "P": [1, 2, 3]}), "CONFIG_ITEMS_TYPE")
        for source in ("[]", "true", "1", '"text"'):
            self.rejected(source, "CONFIG_ROOT_TYPE")
        for source in ("{}", '{"export_dir":""}'):
            self.rejected(source, "CONFIG_PRODUCT_CAPACITY")

    def test_explicit_empty_catalog_is_a_valid_version(self):
        parsed = self.parse('{"items":[]}')
        self.assertEqual(parsed.status, "ok")
        self.assertEqual(parsed.config.prices.price_version_id, "v1")
        self.assertEqual(len(parsed.config.prices.items), 0)

    def test_bad_item_missing_fields_and_unknown_fields_reject_all_items(self):
        for bad in (None, False, 1, [], "item"):
            self.rejected(document(item(), bad), "CONFIG_ITEM_TYPE", "items[1]")
        for field in ("name", "sale", "cost"):
            candidate = item()
            del candidate[field]
            self.rejected(document(candidate), field=f"items[0].{field}")
        self.rejected(document(item(), item("Q", hidden="ignored")), "CONFIG_UNKNOWN_FIELD", "items[1].hidden")
        self.rejected(document(item(), hidden={"ignored": 1}), "CONFIG_UNKNOWN_FIELD", "hidden")
        for name in (True, 12, None, "   "):
            self.rejected(document(item(name)), field="items[0].name")

    def test_single_and_qty_only_are_strict_booleans(self):
        for flag in ("single", "qty_only"):
            for value in ("false", "true", 0, 1, None):
                candidate = {"name": "P", "sale": "1", "cost": "0", flag: value}
                with self.subTest(flag=flag, value=value):
                    self.rejected(document(candidate), "SINGLE_NOT_BOOLEAN", f"items[0].{flag}")
            for value in (True, False):
                candidate = {"name": "P", "sale": "1", "cost": "0", flag: value}
                self.assertIs(self.parse(document(candidate)).config.prices.items[0].single, value)
        self.rejected(document({"name": "P", "sale": "1", "cost": "0", "single": False, "qty_only": True}),
                      "SINGLE_FLAGS_CONFLICT")
        self.assertTrue(self.parse(document({"name": "P", "sale": "1", "cost": "0", "single": True, "qty_only": True})).config.prices.items[0].single)
        self.assertFalse(self.parse(document({"name": "P", "sale": "1", "cost": "0"})).config.prices.items[0].single)

    def test_trimmed_duplicate_and_reserved_names_block_publication(self):
        self.rejected(document(item("A"), item(" A ")), "PRODUCT_NAME_DUPLICATE", "items[1].name")
        self.rejected('{"A":[1,0,1]," A ":[1,0,1]}', "PRODUCT_NAME_DUPLICATE", legacy_single_names=())
        for name in ("折扣", " 折扣 "):
            self.rejected(document(item(name)), "PRODUCT_NAME_RESERVED")
            self.rejected(json.dumps({name: [1, 0, 1]}), "PRODUCT_NAME_RESERVED", legacy_single_names=())
        # In an explicit items array these names cannot collide with metadata.
        self.assertEqual(self.parse(document(item("items"), item("export_dir"))).status, "ok")
        self.rejected('{"export_dir":[1,0,1],"P":[1,0,1]}', field="export_dir", legacy_single_names=())

    def test_json_duplicate_keys_and_nonfinite_constants_are_never_silently_accepted(self):
        for source in ('{"items":[],"items":[]}', '{"P":[1,0,1],"P":[2,0,1]}',
                       '{"items":[{"name":"P","sale":1,"sale":2,"cost":0}]}'):
            self.rejected(source, "JSON_DUPLICATE_KEY", "json")
        for token in ("NaN", "Infinity", "-Infinity"):
            self.rejected('{"items":[{"name":"P","sale":'+token+',"cost":0}]}', "JSON_NON_FINITE")

    def test_financial_types_bounds_scale_and_unsafe_expressions_use_numeric_v1(self):
        bad = [(True, "CONFIG_NUMBER_TYPE"), (None, "CONFIG_NUMBER_TYPE"), ([], "CONFIG_NUMBER_TYPE"),
               ("", "EMPTY"), ("-1", "FIELD_RANGE"), ("1/0", "DIVISION_BY_ZERO"),
               ("1e10", "LITERAL_EXPONENT"), ("0.0000000000001", "LITERAL_CAPACITY"),
               ("nan", "UNSUPPORTED_NODE"), ('__import__("os")', "UNSUPPORTED_NODE"),
               ("1e9*1e9*1e9*1e9*1e9*1e9", "INTERMEDIATE_CAPACITY")]
        for field in ("sale", "cost", "k"):
            for value, reason in bad:
                if field == "k" and value == "":
                    continue
                candidate = item()
                candidate[field] = value
                with self.subTest(field=field, value=value):
                    self.rejected(document(candidate), reason, f"items[0].{field}")
        self.assertEqual(self.parse(document({"name":"P", "sale":1000000000, "cost":0, "k":"1"})).status, "ok")
        loss = self.parse(document({"name":"P", "sale":"1", "cost":"2", "single":True})).config
        self.assertEqual(calculate_quote(QuoteSnapshot("v1", (NormalLine("P", "0.5"),)), loss.prices).totals.profit_cents, -50)

    def test_missing_or_blank_k_is_one_but_unused_blank_prices_block_whole_config(self):
        for k in (None, "", "   "):
            candidate = item()
            if k is not None:
                candidate["k"] = k
            config = self.parse(document(candidate)).config
            self.assertEqual(parse_number(config.prices.items[0].k, empty_k=True), Decimal(1))
        unused = item("unused")
        unused["sale"] = ""
        self.rejected(document(item(), unused), "EMPTY", "items[1].sale")
        # Calculation still validates only referenced prices; publication is whole-file.
        direct = PriceSnapshot("v1", (PriceItem("P", "50", "20", single=True), PriceItem("unused", "", "")))
        self.assertEqual(calculate_quote(QuoteSnapshot("v1", (NormalLine("P", "1"),)), direct).status, "ok")

    def test_invalid_refresh_preserves_identical_valid_snapshot_and_raw_source(self):
        raw = document(item(), export_dir="E:\\原目录").replace('"items":', '\r\n"items":')
        previous = self.parse(raw).config
        for bad in ('{"items":{}}', document(item("changed"), None), "broken"):
            refresh = refresh_price_config(previous, bad, price_version_id="v2")
            self.assertFalse(refresh.applied)
            self.assertIs(refresh.active, previous)
            self.assertIsNone(refresh.validation.config)
            self.assertEqual(previous.original_json, raw)
            self.assertEqual(previous.prices.price_version_id, "v1")
        first = refresh_price_config(None, "broken", price_version_id="v1")
        self.assertIsNone(first.active)
        self.assertFalse(first.applied)
        with self.assertRaises(TypeError):
            refresh_price_config({}, raw, price_version_id="v2")

    def test_valid_refresh_replaces_all_prices_and_metadata_without_mutating_previous(self):
        previous = self.parse(document(item())).config
        fresh = refresh_price_config(previous, document(item("Q"), export_dir=""), price_version_id="v2")
        self.assertTrue(fresh.applied)
        self.assertIs(fresh.active, fresh.validation.config)
        self.assertIsNot(fresh.active, previous)
        self.assertEqual([p.product_id for p in fresh.active.prices.items], ["Q"])
        self.assertEqual(fresh.active.export_dir, "")
        self.assertEqual(previous.prices.items[0].product_id, "P")
        for instance, field, value in ((fresh.active, "export_dir", "changed"),
                                       (fresh.active.prices.items[0], "sale", "changed")):
            with self.assertRaises(FrozenInstanceError):
                setattr(instance, field, value)

    def test_json_numbers_preserve_exact_original_tokens_and_no_float_roundtrip(self):
        raw = '{"items":[{"name":"P","sale":999999999.999999999999,"cost":0.123456789012,"single":true}]}'
        parsed = self.parse(raw)
        self.assertEqual(parsed.status, "ok")
        price = parsed.config.prices.items[0]
        self.assertEqual(price.sale, "999999999.999999999999")
        self.assertEqual(price.cost, "0.123456789012")
        self.assertEqual(parse_number(price.sale), Decimal("999999999.999999999999"))
        self.rejected('{"items":[{"name":"P","sale":1e999,"cost":0}]}', "LITERAL_EXPONENT")

    def test_utf8_bom_chinese_crlf_and_bad_sources_have_explicit_results(self):
        raw = "\ufeff" + document(item("中文")).replace('{', '{\r\n', 1)
        self.assertEqual(self.parse(raw.encode("utf-8")).config.original_json, raw)
        self.rejected(document(item("中文")).encode("gbk"), "JSON_ENCODING")
        for source in (None, False, {}, bytearray(b"{}")):
            self.rejected(source, "JSON_SOURCE_TYPE")
        self.rejected(b"\xff", "JSON_ENCODING")
        self.rejected("", "JSON_SYNTAX")

    def test_byte_depth_number_and_item_capacity_are_checked_before_later_work(self):
        with patch.object(config_module, "CONFIG_BYTE_LIMIT", 10), patch.object(config_module.json, "loads") as load:
            self.rejected('"中中中"', "JSON_BYTE_CAPACITY")
            load.assert_not_called()
        with patch.object(config_module.json, "loads") as load:
            self.rejected("[" * 33 + "]" * 33, "JSON_DEPTH_CAPACITY")
            load.assert_not_called()
        with patch.object(config_module, "parse_number") as parse:
            self.rejected('{"items":[{"name":"P","sale":'+"1"*257+',"cost":0}]}', "JSON_NUMBER_CAPACITY")
            parse.assert_not_called()
        with patch.object(config_module, "PRODUCT_LIMIT", 2), patch.object(config_module, "parse_number") as parse:
            self.rejected(document(item("A"), item("B"), item("C")), "CONFIG_PRODUCT_CAPACITY")
            parse.assert_not_called()
        name = 'A[\\"' * 30
        self.assertEqual(self.parse(document(item(name))).status, "ok")

    def test_names_versions_and_directory_text_are_validated_without_path_io(self):
        for name in ("P\n", "P\x00", "P" * 257):
            self.rejected(document(item(name)), field="items[0].name")
        self.rejected(json.dumps({"items": [item("\ud800")]}), "CONFIG_TEXT_ENCODING", "items[0].name")
        for version in (None, True, "", " v1 ", "V" * 257):
            self.assertEqual(parse_price_config(document(item()), price_version_id=version).status, "VALIDATION")
        for export_dir in (False, 12, None, "E:\\bad\x00"):
            self.rejected(document(item(), export_dir=export_dir), field="export_dir")
        with patch("builtins.open", side_effect=AssertionError("filesystem access")):
            absent = self.parse(document(item()))
            present = self.parse(document(item(), export_dir=r"relative\利润表"))
        self.assertIsNone(absent.config.export_dir)
        self.assertEqual(present.config.export_dir, r"relative\利润表")

    def test_line_kind_is_fixed_in_serialization_and_independent_of_names(self):
        normal, discount = NormalLine("P", "1", name="折扣"), DiscountLine("90", name="普通项目")
        self.assertEqual(asdict(normal)["line_kind"], "normal")
        self.assertEqual(asdict(discount)["line_kind"], "discount")
        prices = self.parse(document(item())).config.prices
        result = calculate_quote(QuoteSnapshot("v1", (normal, discount)), prices)
        self.assertEqual(result.totals.income_cents, 4500)
        with self.assertRaises(TypeError):
            NormalLine("P", "1", line_kind="discount")
        with self.assertRaises(ValueError):
            replace(normal, line_kind="discount")
        row = {"row_kind":"normal", "display_name":"折扣", "base_type":"P", "q":"1"}
        captured = capture_legacy_quote([row], {"P":{"sale":"50","cost":"20","single":True}}, price_version_id="v1")
        self.assertEqual(captured[0].lines[0].line_kind, "normal")

    def test_original_readers_reproduce_bad_boolean_or_item_shape_and_new_parser_rejects(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import baseline_check
        manifest = json.loads((ROOT / "docs/baseline/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            with self.subTest(role=entry["role"]), tempfile.TemporaryDirectory() as folder:
                sandbox = Path(folder)
                ns = baseline_check.sandbox_namespace(ROOT, entry, sandbox)
                obj = ns["PriceCalculator"].__new__(ns["PriceCalculator"])
                obj.default_items = [{"name":"P", "sale":"1", "cost":"0", "single":False}]
                obj.config_file = str(sandbox / "reader-config.json")
                captured = []
                obj.add_setting_row = lambda **row: captured.append(row)
                bad = {"items":[{"name":"P", "sale":"1", "cost":"0", "single":"false"}]}
                if entry["role"] == "sales":
                    self.assertTrue(obj.convert_price_items_from_json(bad)[0]["single"])
                    self.assertEqual(obj.convert_price_items_from_json({"items":[None]}), [])
                else:
                    Path(obj.config_file).write_text(json.dumps(bad), encoding="utf-8")
                    obj.load_settings_to_ui()
                    self.assertTrue(captured[0]["single"])
                    Path(obj.config_file).write_text('{"items":[null]}', encoding="utf-8")
                    with self.assertRaises(AttributeError):
                        obj.load_settings_to_ui()
                self.rejected(json.dumps(bad), "SINGLE_NOT_BOOLEAN")
                self.rejected('{"items":[null]}', "CONFIG_ITEM_TYPE")

    def test_shared_discount_parser_and_json_errors_do_not_leak_input_excerpts(self):
        self.assertEqual(parse_percent("88.555555555555%"), Decimal("88.555555555555"))
        for raw in (True, "1+2", "", "101", "-1", "nan"):
            with self.assertRaises(ValueError):
                parse_percent(raw)
        result = self.rejected('{"客户机密": broken}', "JSON_SYNTAX")
        self.assertNotIn("客户机密", repr(result))


if __name__ == "__main__":
    unittest.main()
