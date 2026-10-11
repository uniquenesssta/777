"""P02-01: shared static targets plus independent arithmetic/snapshot checks."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, FloatOperation, Inexact, ROUND_DOWN, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from quote_core import (
    Amounts, DiscountLine, NormalLine, PriceItem, PriceSnapshot, QuoteSnapshot,
    calculate_quote, capture_legacy_quote,
)
from quote_core import numbers
import p01_oracle as oracle

SUITE = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))


def golden_inputs(case):
    lines = tuple(DiscountLine(line["percent"]) if line["kind"] == "discount" else
                  NormalLine(line["product_id"], line["q"], line.get("h", ""), line.get("w", ""))
                  for line in case["input"])
    prices = PriceSnapshot(case["price_snapshot"]["price_version_id"], tuple(
        PriceItem(key, value["sale"], value["cost"], value["k"], value["single"])
        for key, value in case["price_snapshot"]["items"].items()))
    # The untouched historical suite uses the candidate ID. P01 approval binds
    # its exact bytes/parameters to numeric-v1; do not alter expected amounts.
    return QuoteSnapshot(prices.price_version_id, lines, case["rule_version"]), prices


class Variable:
    def __init__(self, value):
        self.value, self.reads = value, 0

    def get(self):
        self.reads += 1
        return self.value


class Unreadable:
    def get(self):
        raise AssertionError("unused dimension/price/result widget was read")


class QuoteCoreTests(unittest.TestCase):
    def test_53_shared_golden_targets_and_money_identities(self):
        self.assertEqual(len(SUITE["cases"]), 53)
        for case in SUITE["cases"]:
            with self.subTest(case=case["id"]):
                snapshot, prices = golden_inputs(case)
                result = calculate_quote(snapshot, prices)
                self.assertEqual(result.display(), case["expected"])
                self.assertEqual(result.numeric_profile, "numeric-v1")
                self.assertEqual(result.price_version_id, prices.price_version_id)
                if result.status == "ok":
                    for field in ("income_cents", "cost_cents", "profit_cents"):
                        self.assertEqual(sum(getattr(line.amounts, field) for line in result.lines),
                                         getattr(result.totals, field))
                    for line in result.lines:
                        self.assertEqual(line.amounts.profit_cents,
                                         line.amounts.income_cents - line.amounts.cost_cents)
                else:
                    self.assertIsNone(result.lines)
                    self.assertIsNone(result.totals)
                    self.assertEqual(result.issues[0].code, "VALIDATION")

    def test_policy_matches_user_adopted_profile_and_hashes(self):
        approval = json.loads((ROOT / "docs/baseline/p01-acceptance.json").read_text(encoding="utf-8"))
        data = (ROOT / approval["numeric_profile"]["source_file"]).read_bytes().replace(b"\r\n", b"\n")
        profile = json.loads(data)
        self.assertEqual(approval["status"], "accepted")
        self.assertEqual(numbers.NUMERIC_PROFILE, approval["numeric_profile"]["effective_id"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), approval["numeric_profile"]["source_sha256"])
        self.assertEqual(hashlib.sha256((ROOT / approval["golden_suite"]["path"]).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                         approval["golden_suite"]["sha256"])
        for attr, key in (("FIELD_SCALE", "field_fraction_digits"), ("DIVISION_SCALE", "division_fraction_digits"),
                          ("INTERMEDIATE_SCALE", "intermediate_fraction_digits"),
                          ("EXACT_PRECISION", "decimal_exact_context_precision"),
                          ("RAW_LIMIT", "raw_character_limit"), ("EXPRESSION_LIMIT", "normalized_character_limit"),
                          ("AST_LIMIT", "ast_node_limit"), ("DEPTH_LIMIT", "ast_depth_limit"),
                          ("LINE_LIMIT", "max_order_lines")):
            self.assertEqual(getattr(numbers, attr), profile[key])
        self.assertEqual(numbers.MONEY_LIMIT, int(profile["max_money_cents"]))
        self.assertEqual(numbers.MAX_FIELD, Decimal(profile["max_field_value"]))
        self.assertEqual(numbers.MAX_INTERMEDIATE, Decimal(profile["max_intermediate_abs"]))

    def test_caller_decimal_precision_rounding_traps_do_not_change_results(self):
        with localcontext() as context:
            context.prec, context.rounding, context.Emax, context.Emin = 3, ROUND_DOWN, 9, -9
            context.traps[Inexact] = context.traps[FloatOperation] = True
            before = context.copy()
            for case in SUITE["cases"]:
                with self.subTest(case=case["id"]):
                    self.assertEqual(calculate_quote(*golden_inputs(case)).display(), case["expected"])
            self.assertEqual(str(context), str(before))

    def test_deterministic_corpus_against_independent_rational_oracle(self):
        rng = random.Random(777)
        for index in range(200):
            sale, cost = rng.randint(0, 5000), rng.randint(0, 5000)
            price = {"sale": f"{sale // 1000}.{sale % 1000:03d}",
                     "cost": f"{cost // 1000}.{cost % 1000:03d}", "k": "1.123456789012", "single": index % 2 == 0}
            case = {"rule_version": "business-v1", "input": [
                {"kind": "normal", "product_id": "P", "q": str(rng.randint(0, 100)), "h": "1.23", "w": "0.45"},
                {"kind": "discount", "percent": str(rng.randint(0, 100))},
                {"kind": "normal", "product_id": "P", "q": "0.123456789012", "h": "1", "w": "2"}],
                "price_snapshot": {"price_version_id": "corpus-v1", "items": {"P": price}}}
            result = calculate_quote(*golden_inputs(case)).display()
            reference = oracle.quote(case)
            self.assertEqual(result, {key: reference[key] for key in result}, index)

    def test_expression_division_remainder_units_and_precision_against_oracle(self):
        expressions = ["1/3*3", "(0-5)%3", "(5)%(0-3)+3", "0.0050000000000",
                       "(1e9*1e9*1e9*1e9*1e9)%3", "￥（10＋5）元", "2米×3m", "12.5%"]
        expressions += [f"({a}/{b})*{b}" for a in range(1, 10) for b in range(2, 10)]
        for text in expressions:
            with self.subTest(text=text):
                try:
                    reference = oracle.number(text)
                except oracle.Validation:
                    with self.assertRaises(numbers.ValidationError):
                        numbers.parse_number(text)
                else:
                    self.assertEqual(Fraction(numbers.parse_number(text)), reference)
        self.assertEqual(numbers.parse_number("(5)%(0-3)+3"), Decimal(2))

    def test_reject_nontext_bool_nonfinite_unsafe_or_unbounded_input(self):
        cases = [True, False, 1.5, Decimal("0.005"), None, "True", "False", "NaN", "Infinity", "1/0",
                 "1%0", "abs(1)", "2**2", "__import__('os')", " " * 257, "1+" * 41 + "1",
                 "-" * 18 + "1", "1e999999999", "1e-13", "0.0000000000001",
                 "1e9*1e9*1e9*1e9*1e9*1e9"]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(numbers.ValidationError):
                numbers.parse_number(text)
        self.assertEqual(numbers.parse_number("", empty_k=True), Decimal(1))
        with self.assertRaises(numbers.ValidationError):
            numbers.parse_number("元", empty_k=True)

    def test_half_ties_are_exact_with_large_and_negative_amounts(self):
        for raw, cents in (("0.005", 1), ("-0.005", -1), ("0.004999999999", 0),
                           ("92233720368547758.07", numbers.MONEY_LIMIT)):
            self.assertEqual(numbers.settle(Decimal(raw)), cents)
        # A tiny amount above a half tie must not turn into a tie at low precision.
        self.assertEqual(numbers.divide(Decimal("0.000000000003"), Decimal(2)), Decimal("0.000000000002"))
        self.assertEqual(numbers.divide(Decimal("-0.000000000003"), Decimal(2)), Decimal("-0.000000000002"))

    def test_exact_context_handles_capacity_proof_and_rejects_excess_afterward(self):
        operand = Decimal("9" * 45 + "." + "9" * 60)
        context = numbers.exact_context()
        product = context.multiply(operand, operand)
        self.assertEqual(Fraction(product), Fraction(operand) ** 2)
        self.assertFalse(context.flags[Inexact])
        with self.assertRaisesRegex(numbers.ValidationError, "INTERMEDIATE_CAPACITY"):
            numbers.checked(product)
        self.assertEqual(numbers.parse_number("(1e9*1e9*1e9*1e9*1e9)%3"), Decimal(1))

    def test_integer_cent_capacity_includes_profit_and_symmetric_negative_limit(self):
        limit = numbers.MONEY_LIMIT
        self.assertEqual(Amounts(limit, 0).cents_payload()["income_cents"], str(limit))
        self.assertEqual(Amounts(-limit, 0).profit_cents, -limit)
        for income, cost in ((limit + 1, 0), (-limit - 1, 0), (-limit, limit), (True, 0)):
            with self.assertRaises(numbers.ValidationError):
                Amounts(income, cost)
        with self.assertRaises(numbers.ValidationError):
            Amounts("1", 0)
        self.assertEqual(Amounts(0, 0).display()["income"], "0.00")

    def test_invalid_second_line_returns_no_partial_authoritative_amounts(self):
        prices = PriceSnapshot("v1", (PriceItem("P", "0.005", "0", single=True),))
        result = calculate_quote(QuoteSnapshot("v1", (NormalLine("P", "1"), NormalLine("P", "1/0"))), prices)
        self.assertEqual(result.status, "VALIDATION")
        self.assertIsNone(result.lines)
        self.assertIsNone(result.totals)
        self.assertEqual((result.issues[0].line_index, result.issues[0].field), (2, "q"))

    def test_versions_and_unknown_product_are_explicit_errors(self):
        snapshot, prices = golden_inputs(SUITE["cases"][0])
        for changed in (replace(snapshot, price_version_id="v-other"),
                        replace(snapshot, rule_version="legacy"), replace(snapshot, numeric_profile="unknown"),
                        replace(snapshot, lines=(NormalLine("missing", "1"),))):
            result = calculate_quote(changed, prices)
            self.assertEqual(result.status, "VALIDATION")
            self.assertIsNone(result.totals)
        duplicate = replace(prices, items=prices.items + prices.items)
        self.assertEqual(calculate_quote(snapshot, duplicate).issues[0].reason, "PRICE_ID_INVALID_OR_DUPLICATE")

    def test_10000_lines_allowed_10001_and_empty_rejected(self):
        prices = PriceSnapshot("v1", (PriceItem("P", "0", "0", single=True),))
        lines = (NormalLine("P", "0"),) * 10000
        result = calculate_quote(QuoteSnapshot("v1", lines), prices)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.lines), 10000)
        for value in (lines + lines[:1], ()):
            self.assertEqual(calculate_quote(QuoteSnapshot("v1", value), prices).status, "VALIDATION")

    def test_snapshots_are_detached_read_once_and_never_read_summary_widgets(self):
        fields = [Variable("2"), Variable("3"), Variable("4")]
        price_fields = [Variable("0.005"), Variable("0"), Variable("1")]
        row = {"row_kind": "normal", "display_name": "A", "base_type": "P",
               "q": fields[0], "h": fields[1], "w": fields[2], "res": Unreadable(), "status": Unreadable()}
        prices = {"P": dict(zip(("sale", "cost", "k"), price_fields), single=False)}
        snapshot, frozen_prices = capture_legacy_quote([row], prices, price_version_id="v1")
        self.assertEqual([f.reads for f in fields + price_fields], [1] * 6)
        fields[0].value = price_fields[0].value = "100"
        row["base_type"] = "changed"
        prices.clear()
        result = calculate_quote(snapshot, frozen_prices)
        self.assertEqual(result.totals.income_cents, 12)
        self.assertEqual([f.reads for f in fields + price_fields], [1] * 6)
        with self.assertRaises(FrozenInstanceError):
            result.totals.income_cents = 10
        result.display()["totals"]["income"] = "999"
        self.assertEqual(result.totals.income_cents, 12)
        with self.assertRaises(numbers.ValidationError):
            NormalLine("P", fields[0])

    def test_shared_price_getters_are_read_once_and_unused_fields_are_ignored(self):
        price_fields = [Variable("10"), Variable("4"), Variable("")]
        config = {"P": dict(zip(("sale", "cost", "k"), price_fields), single=True),
                  "unused": {"sale": Unreadable()}}
        rows = [{"base_type": "P", "q": Variable("1"), "h": Unreadable(), "w": Unreadable()} for _ in range(2)]
        snapshot, prices = capture_legacy_quote(rows, config, price_version_id="v1")
        self.assertEqual([f.reads for f in price_fields], [1, 1, 1])
        self.assertEqual(calculate_quote(snapshot, prices).totals.income_cents, 2000)
        self.assertEqual(len(prices.items), 1)

    def test_discount_capture_preserves_precision_and_does_not_read_disabled_fields(self):
        choice, custom = Variable("自定义"), Variable("88.555555555555%")
        rows = [{"row_kind": "discount", "discount_choice": choice, "discount_custom": custom,
                 "q": Unreadable(), "h": Unreadable(), "w": Unreadable()}]
        snapshot, prices = capture_legacy_quote(rows, {}, price_version_id="v1")
        self.assertEqual((choice.reads, custom.reads), (1, 1))
        result = calculate_quote(snapshot, prices)
        self.assertEqual(dict(result.lines[0].normalized)["percent"], "88.555555555555")
        self.assertEqual(result.warnings[0].reason, "DISCOUNT_ZERO_SUBTOTAL")
        rows[0]["discount_choice"] = Variable("90%")
        rows[0]["discount_custom"] = Unreadable()
        self.assertEqual(capture_legacy_quote(rows, {}, price_version_id="v1")[0].lines[0].percent, "90%")

    def test_sequence_inputs_copied_and_invalid_mutable_values_rejected(self):
        line = NormalLine("P", "1")
        raw_lines = [line]
        items = [PriceItem("P", "1", "0", single=True)]
        snapshot, prices = QuoteSnapshot("v1", raw_lines), PriceSnapshot("v1", items)
        raw_lines.clear(); items.clear()
        self.assertEqual(calculate_quote(snapshot, prices).totals.income_cents, 100)
        with self.assertRaises(numbers.ValidationError):
            NormalLine("P", [])
        with self.assertRaises(numbers.ValidationError):
            PriceSnapshot("v1", [{}])
        with self.assertRaises(numbers.ValidationError):
            QuoteSnapshot("v1", iter([line]))

    def test_core_import_and_calculation_with_only_standard_library_no_repo_asset_reads(self):
        script = """
import builtins, sys
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'tkinter', 'openpyxl', 'PIL', 'tools', 'p01_oracle'}:
        raise AssertionError('forbidden dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from quote_core import *
def no_asset_reads(*args, **kwargs):
    raise AssertionError('calculation tried filesystem I/O')
builtins.open = no_asset_reads
prices = PriceSnapshot('v1', (PriceItem('P', '0.005', '0', single=True),))
result = calculate_quote(QuoteSnapshot('v1', (NormalLine('P', '1'),)), prices)
assert result.totals.income_cents == 1
assert result.numeric_profile == 'numeric-v1'
validated = parse_price_config('{"items":[{"name":"P","sale":"0.005","cost":"0","single":true}]}', price_version_id='v1')
assert validated.status == 'ok'
assert calculate_quote(QuoteSnapshot('v1', (NormalLine('P', '1'),)), validated.config.prices).totals.income_cents == 1
retained = refresh_price_config(validated.config, '{"items":false}', price_version_id='v2')
assert not retained.applied and retained.active is validated.config
session = QuoteSession(QuoteSnapshot('v1', (NormalLine('P', '1'),)), validated.config.prices,
                       price_source='current', latest_price_version_id='v1')
session.calculate()
assert session.dispatch_output('excel', lambda payload: payload.result.totals.income_cents) == 1
session.invalidate_inputs()
try:
    session.dispatch_output('screenshot', lambda payload: (_ for _ in ()).throw(AssertionError('writer called')))
except OutputBlocked as error:
    assert error.decision.status == 'CALCULATION_STALE'
else:
    raise AssertionError('stale screenshot was accepted')
print('standalone core passed')
"""
        with tempfile.TemporaryDirectory(prefix="777-core-only-") as folder:
            shutil.copytree(ROOT / "quote_core", Path(folder) / "quote_core",
                            ignore=shutil.ignore_patterns("__pycache__"))
            process = subprocess.run([sys.executable, "-S", "-c", script, folder],
                                     text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(process.stdout.strip(), "standalone core passed")


if __name__ == "__main__":
    unittest.main()
