"""P02-03 draft revision, price-state and zero-side-effect output checks."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from quote_core import (
    Amounts, CalculationCompletion, DiscountLine, DraftDetails, Issue, NormalLine,
    OutputBlocked, PriceItem, PriceSnapshot, QuoteSession, QuoteSnapshot,
    parse_price_config, refresh_price_config, run_calculation,
)
import baseline_check

KINDS = ("excel", "quote_image", "screenshot")


def prices(version="v1", sale="10", cost="4"):
    return PriceSnapshot(version, (PriceItem("P", sale, cost, "1", True),))


def snapshot(*lines, version="v1"):
    return QuoteSnapshot(version, lines or (NormalLine("P", "1"),))


class QuoteSessionTests(unittest.TestCase):
    def ready(self, quote=None, catalog=None, **kwargs):
        session = QuoteSession(snapshot() if quote is None else quote,
                               prices() if catalog is None else catalog,
                               price_source="current", latest_price_version_id=(
                                   "v1" if catalog is None else catalog.price_version_id), **kwargs)
        session.calculate()
        return session

    def blocked(self, session, code=None, reason=None):
        for kind in KINDS:
            writer = Mock(side_effect=AssertionError("blocked writer was invoked"))
            decision = session.prepare_output(kind)
            self.assertFalse(decision.allowed)
            self.assertIsNone(decision.payload)
            if code is not None:
                self.assertEqual(decision.status, code)
            if reason is not None:
                self.assertIn(reason, [issue.reason for issue in decision.issues])
            with self.assertRaises(OutputBlocked) as error:
                session.dispatch_output(kind, writer)
            self.assertEqual(error.exception.decision, decision)
            writer.assert_not_called()
        return decision

    def test_empty_and_uncalculated_drafts_never_invoke_any_writer(self):
        self.blocked(QuoteSession(), "VALIDATION", "PRICE_SOURCE_UNVERIFIED")
        session = QuoteSession(snapshot(), prices(), price_source="current", latest_price_version_id="v1")
        self.assertEqual(session.state.status, "uncalculated")
        self.blocked(session, "VALIDATION", "CALCULATION_REQUIRED")
        session.calculate()
        self.assertTrue(session.prepare_output("excel").allowed)

    def test_valid_outputs_share_frozen_integer_cent_result_and_text_identity(self):
        details = DraftDetails("000012", "00003", "微信")
        session = self.ready(snapshot(NormalLine("P", "1"), NormalLine("P", "1")),
                             prices(sale="0.005", cost="0"), details=details)
        before = session.state
        self.assertEqual(before.status, "valid")
        self.assertEqual(before.result.totals.income_cents, 2)
        for kind in KINDS:
            writer = Mock(side_effect=lambda payload: payload.result.totals.cents_payload())
            self.assertEqual(session.dispatch_output(kind, writer)["income_cents"], "2")
            payload = writer.call_args.args[0]
            self.assertIs(payload.result, before.result)
            self.assertIs(payload.snapshot, before.snapshot)
            self.assertIs(payload.prices, before.prices)
            self.assertIs(payload.details, details)
            self.assertEqual(payload.revision, before.calculation_revision)
            writer.assert_called_once()
        # A real synthetic workbook consumes the same integer-cent payload.
        import openpyxl
        with tempfile.TemporaryDirectory(prefix="777-p02-valid-") as folder:
            target = Path(folder) / "valid.xlsx"
            def write_excel(payload):
                workbook = openpyxl.Workbook()
                try:
                    for line in payload.result.lines:
                        workbook.active.append([line.sequence, line.raw.line_kind,
                                                line.amounts.cents_payload()["income_cents"]])
                    workbook.active.append(["total", payload.details.customer,
                                            payload.result.totals.cents_payload()["income_cents"]])
                    workbook.save(target)
                finally:
                    workbook.close()
                return target
            self.assertEqual(session.dispatch_output("excel", write_excel), target)
            workbook = openpyxl.load_workbook(target, read_only=True)
            try:
                self.assertEqual(list(workbook.active.values), [(1, "normal", "1"),
                                 (2, "normal", "1"), ("total", "000012", "2")])
            finally:
                workbook.close()

    def test_one_valid_one_invalid_has_no_authoritative_amounts_or_file_changes(self):
        with tempfile.TemporaryDirectory(prefix="777-p02-invalid-") as folder:
            target = Path(folder) / "existing.xlsx"
            target.write_bytes(b"existing ledger must remain unchanged")
            original = target.read_bytes()
            for lines, index in (((NormalLine("P", "1"), NormalLine("P", "bad")), 2),
                                 ((NormalLine("P", "bad"), NormalLine("P", "1")), 1)):
                session = self.ready(QuoteSnapshot("v1", lines))
                self.assertEqual(session.state.status, "invalid")
                self.assertIsNone(session.state.result.lines)
                self.assertIsNone(session.state.result.totals)
                self.assertEqual(session.state.result.issues[0].line_index, index)
                self.assertEqual(session.state.result.issues[0].field, "q")
                self.blocked(session, "VALIDATION")
                writer = Mock(side_effect=lambda payload: target.write_bytes(b"wrong partial order"))
                with self.assertRaises(OutputBlocked):
                    session.dispatch_output("excel", writer)
                writer.assert_not_called()
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_invalid_discount_discards_all_prior_lines_and_points_to_input_row(self):
        for bad in ("bad", "", "101", "1/0", True):
            session = self.ready(snapshot(NormalLine("P", "1"), DiscountLine("90"), DiscountLine(bad)))
            result = session.state.result
            self.assertIsNone(result.lines)
            self.assertIsNone(result.totals)
            self.assertEqual(result.issues[0].line_index, 3)
            self.assertEqual(result.issues[0].field, "percent")
            self.blocked(session, "VALIDATION")
        for quote in (snapshot(DiscountLine("90"), NormalLine("P", "1")),
                      snapshot(NormalLine("P", "1"), DiscountLine("0")),
                      snapshot(NormalLine("P", "0"))):
            session = self.ready(quote)
            self.assertTrue(session.prepare_output("excel").allowed)
        self.assertTrue(self.ready(catalog=prices(sale="1", cost="4")).prepare_output("excel").allowed)

    def test_input_changes_and_change_back_require_new_calculation(self):
        session = self.ready()
        previous = session.prepare_output("excel").payload
        for quote in (snapshot(NormalLine("P", "2")), snapshot()):
            revision = session.state.revision
            session.update_inputs(quote)
            self.assertEqual(session.state.revision, revision + 1)
            self.assertEqual(session.state.status, "stale")
            self.assertIsNone(session.state.result)
            self.assertIsNone(session.state.calculation_revision)
            self.blocked(session, "CALCULATION_STALE")
        self.assertEqual(previous.result.totals.income_cents, 1000)
        session.calculate()
        self.assertTrue(session.prepare_output("excel").allowed)
        self.assertGreater(session.state.calculation_revision, previous.revision)

    def test_metadata_edits_and_capture_failure_invalidate_without_widget_reads(self):
        session = self.ready(details=DraftDetails("甲", "001", "微信"))
        session.update_details(DraftDetails("乙", "002", "新微信"))
        self.blocked(session, "CALCULATION_STALE")
        session.calculate()
        self.assertEqual(session.prepare_output("excel").payload.details.order_ref, "002")
        issues = [Issue("VALIDATION", "SNAPSHOT_TEXT_TYPE", "q", 2)]
        session.invalidate_inputs(issues)
        issues.clear()
        self.assertEqual(session.state.status, "invalid")
        self.assertIsNone(session.state.snapshot)
        self.assertIsNone(session.state.result)
        self.blocked(session, "VALIDATION", "SNAPSHOT_TEXT_TYPE")
        session.calculate()
        self.assertIsNone(session.state.result.totals)
        self.assertEqual(session.state.result.issues[0].line_index, 2)
        session.update_inputs(snapshot())
        session.calculate()
        self.assertTrue(session.prepare_output("excel").allowed)

    def test_offline_unverified_and_bad_price_sources_block_cached_calculation(self):
        session = self.ready()
        cached = session.state.prices
        for source, code, reason in (("unavailable", "IO_UNAVAILABLE", "PRICES_UNAVAILABLE"),
                                     ("unverified", "VALIDATION", "PRICE_SOURCE_UNVERIFIED"),
                                     ("invalid", "VALIDATION", "PRICE_CONFIG_INVALID")):
            session.observe_price_source(source, latest_price_version_id="v1")
            self.assertIs(session.state.prices, cached)
            self.assertIsNone(session.state.result)
            session.calculate()  # Cached numeric calculation is only a draft preview.
            self.assertEqual(session.state.status, "valid")
            self.blocked(session, code, reason)
        session.observe_price_source("current", latest_price_version_id="v1")
        self.blocked(session, "CALCULATION_STALE")
        session.calculate()
        self.assertTrue(session.prepare_output("excel").allowed)

    def test_observed_version_changes_never_rebind_or_revive_an_old_result(self):
        session = self.ready()
        old_quote, old_prices = session.state.snapshot, session.state.prices
        for version in ("v2", "v1"):
            session.observe_price_source("current", latest_price_version_id=version)
            self.assertIs(session.state.snapshot, old_quote)
            self.assertIs(session.state.prices, old_prices)
            self.assertIsNone(session.state.result)
            self.blocked(session, "PRICE_STALE" if version == "v2" else "CALCULATION_STALE")
        session.calculate()
        revision = session.state.revision
        session.observe_price_source("current", latest_price_version_id="v1")
        self.assertEqual(session.state.revision, revision)  # Identical observation is a no-op.
        self.assertTrue(session.prepare_output("excel").allowed)

    def test_price_refresh_requires_current_recalculation_and_revision_confirmation(self):
        session = self.ready()
        old = session.prepare_output("excel").payload
        session.observe_price_source("current", latest_price_version_id="v2")
        session.calculate()
        self.blocked(session, "PRICE_STALE")
        session.refresh_prices(prices("v2", sale="12"))
        self.assertEqual(session.state.snapshot.price_version_id, "v2")
        self.assertTrue(session.state.price_confirmation_required)
        self.assertFalse(session.confirm_prices(expected_revision=session.state.revision))
        session.calculate()
        current = session.state.revision
        self.blocked(session, "VALIDATION", "PRICE_CONFIRMATION_REQUIRED")
        self.assertFalse(session.confirm_prices(expected_revision=old.revision))
        self.assertTrue(session.confirm_prices(expected_revision=current))
        self.assertEqual(session.prepare_output("excel").payload.result.totals.income_cents, 1200)
        self.assertEqual(old.result.totals.income_cents, 1000)
        self.assertEqual(old.prices.price_version_id, "v1")
        session.observe_price_source("current", latest_price_version_id="v3")
        self.assertFalse(session.confirm_prices(expected_revision=current))
        self.blocked(session, "PRICE_STALE")

    def test_same_version_price_replacement_still_invalidates_and_needs_confirmation(self):
        session = self.ready()
        revision = session.state.revision
        session.refresh_prices(prices(sale="15"))
        self.assertGreater(session.state.revision, revision)
        self.blocked(session, "CALCULATION_STALE")
        session.calculate()
        self.blocked(session, "VALIDATION", "PRICE_CONFIRMATION_REQUIRED")
        self.assertTrue(session.confirm_prices(expected_revision=session.state.revision))
        session.update_inputs(snapshot(NormalLine("P", "2")))
        session.calculate()
        # Confirmed price consent persists; an input edit still required recalculation.
        self.assertEqual(session.prepare_output("excel").payload.result.totals.income_cents, 3000)

    def test_failed_configuration_refresh_retains_prices_but_never_authorizes_output(self):
        good = parse_price_config('{"items":[{"name":"P","sale":10,"cost":4,"single":true}]}',
                                  price_version_id="v1").config
        session = self.ready(catalog=good.prices)
        failed = refresh_price_config(good, '{"items":false}', price_version_id="v2")
        self.assertIs(failed.active, good)
        self.assertFalse(failed.applied)
        session.observe_price_source("invalid", latest_price_version_id="v1")
        session.calculate()
        self.assertIs(session.state.prices, good.prices)
        self.blocked(session, "VALIDATION", "PRICE_CONFIG_INVALID")
        session.observe_price_source("current", latest_price_version_id="v1")
        self.blocked(session, "CALCULATION_STALE")

    def test_late_and_cross_draft_workers_cannot_replace_current_result_or_error(self):
        session = self.ready()
        old_request = session.begin_calculation()
        session.update_inputs(snapshot(NormalLine("P", "2")))
        session.calculate()
        current = session.state.result
        self.assertFalse(session.apply_calculation(run_calculation(old_request)))
        self.assertIs(session.state.result, current)
        other = self.ready(snapshot(NormalLine("P", "2")))
        self.assertFalse(session.apply_calculation(run_calculation(other.begin_calculation())))
        session.update_inputs(snapshot(NormalLine("P", "bad")))
        session.calculate()
        invalid = session.state.result
        self.assertFalse(session.apply_calculation(run_calculation(old_request)))
        self.assertIs(session.state.result, invalid)
        self.blocked(session, "VALIDATION")
        session.update_inputs(old_request.snapshot)  # Same values, later revision (ABA).
        self.assertFalse(session.apply_calculation(run_calculation(old_request)))

    def test_initial_unverified_missing_and_mismatched_versions_fail_closed(self):
        session = QuoteSession(snapshot(), prices())
        session.calculate()
        self.blocked(session, "VALIDATION", "PRICE_SOURCE_UNVERIFIED")
        session.observe_price_source("current")  # An absent published ID proves nothing.
        session.calculate()
        self.blocked(session, "VALIDATION", "PRICE_SOURCE_UNVERIFIED")
        mismatched = self.ready(snapshot(version="v2"))
        self.blocked(mismatched, "VALIDATION", "PRICE_VERSION_MISMATCH")
        empty = self.ready(QuoteSnapshot("v1", ()))
        self.blocked(empty, "VALIDATION", "LINE_CAPACITY")
        no_prices = QuoteSession(snapshot(), price_source="current", latest_price_version_id="v1")
        self.blocked(no_prices, "VALIDATION", "PRICE_SNAPSHOT_REQUIRED")
        no_prices.calculate()
        self.assertEqual(no_prices.state.result.issues[0].field, "prices")
        self.blocked(no_prices, "VALIDATION", "PRICE_SNAPSHOT_REQUIRED")

    def test_api_bad_types_are_atomic_and_output_kind_cannot_bypass_the_gate(self):
        session = self.ready()
        before = session.state
        operations = (
            lambda: session.update_inputs({}),
            lambda: session.update_inputs(snapshot(), details={}),
            lambda: session.update_details(DraftDetails(customer=123)),
            lambda: session.refresh_prices({}),
            lambda: session.invalidate_inputs([Issue("WARNING", "X", "q")]),
            lambda: session.observe_price_source(True, latest_price_version_id="v1"),
            lambda: session.observe_price_source("current", latest_price_version_id=True),
            lambda: session.observe_price_source("current", latest_price_version_id=" v1 "),
            lambda: session.observe_price_source("current", latest_price_version_id="\ud800"),
            lambda: session.confirm_prices(expected_revision=True),
            lambda: session.prepare_output("draft_screenshot"),
            lambda: session.dispatch_output("excel", None),
            lambda: session.apply_calculation({}),
            lambda: run_calculation({}),
        )
        for operation in operations:
            with self.assertRaises((TypeError, ValueError)):
                operation()
            self.assertEqual(session.state, before)
        for record in (before, session.begin_calculation(), session.prepare_output("excel"),
                       session.prepare_output("excel").payload, before.details):
            with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
                record.revision = 100

    def test_cached_decisions_do_not_authorize_later_dispatch_and_writer_errors_propagate(self):
        session = self.ready()
        cached = session.prepare_output("excel")
        session.invalidate_inputs()
        self.assertTrue(cached.allowed)  # An immutable historical decision, not a capability.
        self.blocked(session, "CALCULATION_STALE")
        session.update_inputs(snapshot())
        session.calculate()
        writer = Mock(side_effect=OSError("synthetic writer failed"))
        with self.assertRaises(OSError):
            session.dispatch_output("excel", writer)
        writer.assert_called_once()
        self.assertEqual(session.state.status, "valid")
        # Persistence/commit-unknown and idempotence belong to file/service tasks.

    def test_incomplete_or_wrong_version_worker_result_cannot_reach_a_writer(self):
        session = self.ready()
        request = session.begin_calculation()
        for result, code in ((replace(session.state.result, lines=None), "VALIDATION"),
                             (replace(session.state.result, price_version_id="v2"), "CALCULATION_STALE"),
                             (replace(session.state.result, rule_version="wrong"), "CALCULATION_STALE"),
                             (replace(session.state.result, totals=Amounts(1, 0)), "VALIDATION"),
                             (replace(session.state.result, lines=(replace(session.state.result.lines[0],
                                       raw=NormalLine("P", "2")),)), "VALIDATION")):
            self.assertTrue(session.apply_calculation(CalculationCompletion(request, result)))
            self.blocked(session, code)
            session.calculate()

    def test_actual_baseline_partial_export_is_reproduced_then_new_gate_writes_zero(self):
        spec = importlib.util.spec_from_file_location("p02_session_audit", ROOT / "docs/audit/reproduce.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        manifest = json.loads((ROOT / "docs/baseline/manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            with self.subTest(role=entry["role"]), tempfile.TemporaryDirectory(prefix="777-p02-output-") as folder:
                root = Path(folder)
                namespace = baseline_check.sandbox_namespace(ROOT, entry, root)
                namespace["messagebox"] = types.SimpleNamespace(
                    showinfo=lambda *args: None, showerror=lambda *args: None, showwarning=lambda *args: None)
                obj = audit.instance(namespace, root)
                obj.get_default_report_dir = lambda: folder
                obj.export_dir_var = audit.Var(folder)
                audit.calculate_rows(obj, ["1", "bad"])
                self.assertEqual(len(obj.last_export_records), 1)
                self.assertEqual(sum(i["级别"] == "错误" for i in obj.validation_issues), 1)
                obj.calculate = lambda: None
                obj.export_to_excel()
                self.assertTrue(Path(obj.get_daily_excel_path()).exists())  # Actual old A04.
                fingerprints = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in root.rglob("*") if p.is_file()}
                quote, catalog = __import__("quote_core").capture_legacy_quote(
                    obj.calc_rows, obj.last_config_snapshot, price_version_id="v1")
                session = self.ready(quote, catalog)
                writer = Mock(side_effect=lambda payload: obj.export_to_excel())
                with self.assertRaises(OutputBlocked):
                    session.dispatch_output("excel", writer)
                writer.assert_not_called()
                self.assertEqual(fingerprints, {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                               for p in root.rglob("*") if p.is_file()})
                self.assertEqual(session.state.result.issues[0].line_index, 2)

    def test_shared_53_golden_cases_flow_through_current_state_and_authoritative_export(self):
        suite = json.loads((ROOT / "docs/baseline/p01-04-golden.json").read_text(encoding="utf-8"))
        self.assertEqual(len(suite["cases"]), 53)
        for case in suite["cases"]:
            with self.subTest(case=case["id"]):
                version = case["price_snapshot"]["price_version_id"]
                catalog = PriceSnapshot(version, tuple(PriceItem(key, value["sale"], value["cost"],
                                        value["k"], value["single"])
                                        for key, value in case["price_snapshot"]["items"].items()))
                lines = tuple(DiscountLine(line["percent"]) if line["kind"] == "discount" else
                              NormalLine(line["product_id"], line["q"], line.get("h", ""), line.get("w", ""))
                              for line in case["input"])
                session = self.ready(QuoteSnapshot(version, lines, case["rule_version"]), catalog)
                self.assertEqual(session.state.result.display(), case["expected"])
                if session.state.result.status != "ok":
                    self.blocked(session, "VALIDATION")
                else:
                    payload = session.dispatch_output("excel", lambda output: output)
                    self.assertIs(payload.result, session.state.result)
                    self.assertEqual(sum(line.amounts.income_cents for line in payload.result.lines),
                                     payload.result.totals.income_cents)


if __name__ == "__main__":
    unittest.main()
