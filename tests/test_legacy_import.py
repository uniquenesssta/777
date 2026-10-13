"""Real source bytes, SQLite, transactions and recovery; synthetic evidence only."""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from quote_core import NormalLine, PriceItem, PriceSnapshot
from quote_ledger import Ledger, Principal
from quote_ledger.paths import Conflict, Forbidden, LedgerError, UnknownCommit
from quote_ledger.backup import Backups, restore_backup
from quote_files.workbooks import table
from quote_import import preview_bytes, apply_source, read_source, batch_request_id
from quote_import.adapters import ReviewRequired
from quote_import.review import write_review
from quote_import.store import verify_provenance
from import_fixture import current_book, legacy_bytes, mutate_bytes, append_note_and_void
from p01_fixtures import workbook


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='777-import-tests-')
        self.root = Path(self.temp.name)
        self.source = current_book(self.root / '原始文件.xlsx')
        self.raw = self.source.read_bytes()
        self.ledger = Ledger.create(self.root / 'ledger.sqlite3')
        self.admin = Principal(str(uuid.uuid4()), 'admin')
        self.owner = str(uuid.uuid4())

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, raw=None, kind='xlsx', **kwargs):
        raw = self.raw if raw is None else raw
        plan = preview_bytes(raw, kind, legacy_single_names=kwargs.get('legacy_single_names'))
        return apply_source(self.ledger, self.admin, self.owner, raw, kind,
                            expected_review_sha256=plan.review_sha256, **kwargs)

    def test_preview_does_not_touch_source_or_database_and_public_report_hides_customer(self):
        before = self.ledger.inventory()
        plan = preview_bytes(read_source(self.source), 'xlsx')
        self.assertEqual(plan.report()['eligible_orders'], 2)
        self.assertEqual(plan.report()['eligible_lines'], 3)
        self.assertNotIn('同秒客户', json.dumps(plan.report(), ensure_ascii=False))
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.ledger.inventory(), before)

    def test_identified_same_second_orders_keep_distinct_ids_and_exact_rows(self):
        result = self.apply()
        inv = self.ledger.inventory()
        self.assertEqual((inv['counts']['orders'], inv['counts']['lines']), (2, 3))
        self.assertEqual((inv['active_income_cents'], inv['active_cost_cents'], inv['active_profit_cents']), ('11100', '4600', '6500'))
        self.assertEqual(result['post_import_inventory'], inv)
        self.assertEqual(len({r['order_id'] for r in result['row_map']}), 2)
        self.assertEqual(len(result['row_map']), 5)
        self.assertEqual(len({r['line_id'] for r in result['row_map'] if r['line_id']}), 3)
        with self.ledger.connection(readonly=True) as c:
            self.assertIsNone(c.execute('SELECT active_price_id FROM ledger_meta').fetchone()[0])
            self.assertTrue(all(r[0] == self.owner for r in c.execute('SELECT owner_id FROM orders')))
            self.assertEqual(verify_provenance(c), 1)

    def test_legacy_tagged_alias_and_reordered_variants_match_exact_amounts(self):
        for options in ({}, {'tagged': True}, {'alias': True}, {'reorder': True}, {'reorder': True, 'tagged': True, 'alias': True}):
            with self.subTest(options=options):
                raw = legacy_bytes(self.raw, **options)
                plan = preview_bytes(raw, 'xlsx')
                self.assertFalse(plan.quarantined)
                self.assertEqual(len(plan.orders), 2)
                self.assertEqual(plan.report()['eligible_active_order_totals_cents'], {'income': '11100', 'cost': '4600', 'profit': '6500'})

    def test_two_same_prefix_without_footer_are_quarantined_not_merged(self):
        raw = legacy_bytes(self.raw, footers=False)
        plan = preview_bytes(raw, 'xlsx')
        self.assertEqual(plan.orders, ())
        self.assertEqual(len(plan.quarantined), 3)
        self.assertTrue(all(i['code'] == 'AMBIGUOUS_ORDER_BOUNDARY' for i in plan.quarantined))
        self.assertEqual(plan.report()['source_read_active_totals_cents']['income_cents'], '11100')
        before = self.ledger.inventory()
        with self.assertRaises(LedgerError):
            self.apply(raw)
        self.assertEqual(self.ledger.inventory(), before)

    def test_two_unidentified_same_prefix_with_explicit_footers_are_distinct(self):
        result = self.apply(legacy_bytes(self.raw))
        self.assertEqual(result['created_orders'], 2)
        self.assertEqual(len({r['order_id'] for r in result['row_map']}), 2)

    def test_empty_P01_evidence_shape_imports_zero_orders_and_preserves_appendices(self):
        path = self.root / 'empty.xlsx'
        workbook(path, 0, variant='empty_evidence_shape')
        result = self.apply(path.read_bytes())
        self.assertEqual(result['created_orders'], 0)
        self.assertEqual(self.ledger.inventory()['counts']['orders'], 0)
        with self.ledger.connection(readonly=True) as c:
            mapping = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
        self.assertIn('价格设定', mapping['file_evidence'])
        self.assertIn('输入问题', mapping['file_evidence'])

    def test_row_and_file_remarks_are_not_assigned_by_last_customer_guess(self):
        raw = legacy_bytes(self.raw)
        def change(book):
            ws = book['利润明细'];ws.cell(6, 27, '备注');ws.cell(7, 27, '原行备注')
            note = book.create_sheet('备注');note.cell(5, 2, '文件说明，归属未知')
        raw = mutate_bytes(raw, change)
        plan = preview_bytes(raw, 'xlsx')
        self.assertEqual(len(plan.orders[0]['notes']), 1)
        self.assertEqual(plan.orders[0]['notes'][0]['body'], '原行备注')
        self.assertEqual(plan.orders[1]['notes'], [])
        self.apply(raw)
        with self.ledger.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT body FROM notes').fetchone()[0], '原行备注')
            metadata = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
            self.assertIn('文件说明，归属未知', json.dumps(metadata['file_evidence'], ensure_ascii=False))

    def test_note_void_event_history_and_source_time_are_preserved(self):
        append_note_and_void(self.source)
        raw = self.source.read_bytes();plan = preview_bytes(raw, 'xlsx')
        self.assertFalse(plan.quarantined)
        self.assertEqual(plan.orders[0]['state'], 'void')
        self.assertEqual(plan.orders[0]['source_revision'], 3)
        result = self.apply(raw)
        self.assertEqual(self.ledger.inventory()['active_income_cents'], '7500')
        self.assertTrue(any('note_id' in m for m in result['row_map']))
        with self.ledger.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT body FROM notes').fetchone()[0], '=原始文字备注')
            row = c.execute('SELECT created_at,revision FROM orders ORDER BY created_at,order_id LIMIT 1').fetchone()
            self.assertEqual(row['created_at'], '2026-10-13T04:00:00+00:00')
            self.assertEqual(row['revision'], 1)
            mapping = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
            self.assertEqual(mapping['orders'][0]['source_revision'], 3)
            self.assertEqual(len(mapping['orders'][0]['source_events']), 3)

    def test_duplicate_source_same_bytes_other_path_has_one_batch_and_original_receipt(self):
        first = self.apply();before = self.ledger.inventory()
        moved = self.root / '重命名副本.xlsx';moved.write_bytes(self.raw)
        self.assertEqual(self.apply(read_source(moved)), first)
        self.assertEqual(self.ledger.inventory(), before)
        self.assertEqual(self.ledger.query_request(batch_request_id(preview_bytes(self.raw, 'xlsx').source_sha256), self.admin), first)

    def test_review_digest_and_owner_are_bound_not_caller_financials(self):
        plan = preview_bytes(self.raw, 'xlsx')
        before = self.ledger.inventory()
        with self.assertRaises(Conflict):
            apply_source(self.ledger, self.admin, self.owner, self.raw, 'xlsx', expected_review_sha256='0' * 64)
        self.assertEqual(self.ledger.inventory(), before)
        self.apply()
        with self.assertRaises(Conflict):
            apply_source(self.ledger, self.admin, str(uuid.uuid4()), self.raw, 'xlsx', expected_review_sha256=plan.review_sha256)

    def test_changed_ooxml_same_stable_orders_reuses_orders_without_duplication(self):
        self.apply();raw = mutate_bytes(self.raw, lambda book: setattr(book.properties, 'title', '新的副本标题'))
        self.assertNotEqual(raw, self.raw)
        result = self.apply(raw)
        self.assertEqual((result['created_orders'], result['reused_identified_orders']), (0, 2))
        self.assertEqual(self.ledger.inventory()['counts']['orders'], 2)
        self.assertEqual(len(result['row_map']), 5)
        with self.ledger.connection(readonly=True) as c:
            self.assertEqual(verify_provenance(c), 2)

    def test_changed_stable_order_is_refused_without_overwriting_existing_rows(self):
        self.apply();before = self.ledger.inventory()
        def change(book):
            _, h = table(book['利润明细']);book['利润明细'].cell(7, h['项目名称'], '改名但同一旧编号')
        raw = mutate_bytes(self.raw, change)
        with self.assertRaises(Conflict):
            self.apply(raw)
        self.assertEqual(self.ledger.inventory(), before)

    def test_new_hash_legacy_lookalike_is_refused_rather_than_merged_or_duplicated(self):
        raw = legacy_bytes(self.raw);self.apply(raw);before = self.ledger.inventory()
        newer = mutate_bytes(raw, lambda book: setattr(book.properties, 'title', '未知来源新副本'))
        with self.assertRaises(Conflict):
            self.apply(newer)
        self.assertEqual(self.ledger.inventory(), before)

    def test_partial_quarantine_requires_explicit_ack_and_keeps_source_difference(self):
        def change(book):
            ws = book['利润明细'];_, h = table(ws)
            for row, income, profit in [(7, '41.00', '25.00'), (9, '37.00', '21.00')]:
                ws.cell(row, h['销售额'], income);ws.cell(row, h['利润'], profit)
            ws.cell(4, 2, '112.00');ws.cell(4, 6, '66.00')
        raw = mutate_bytes(self.raw, change);plan = preview_bytes(raw, 'xlsx')
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.quarantined[0]['code'], 'HISTORICAL_AMOUNT_DIFFERS_FROM_CORE')
        self.assertEqual(plan.quarantined[0]['difference']['source_cents'], ['4100', '1600', '2500'])
        self.assertEqual(plan.quarantined[0]['difference']['core_cents'], ['4000', '1600', '2400'])
        with self.assertRaises(LedgerError):self.apply(raw)
        result = self.apply(raw, allow_quarantine=True)
        self.assertEqual(result['created_orders'], 1)
        self.assertEqual(result['source_read_active_totals_cents']['income_cents'], '11200')
        self.assertEqual(self.ledger.inventory()['active_income_cents'], '7500')

    def test_same_named_footer_typed_product_remains_normal_line(self):
        p = current_book(self.root / 'named.xlsx', [(NormalLine('单件', '1', name='--- 本次总计 ---'),)])
        result = self.apply(p.read_bytes())
        self.assertEqual(result['eligible_lines'], 1)
        self.assertEqual(self.ledger.inventory()['counts']['lines'], 1)

    def test_invalid_identity_summary_receipt_and_unknown_sheet_are_source_quarantines(self):
        def identity(book):
            _, h = table(book['利润明细']);book['利润明细'].cell(7, h['明细ID'], 'bad')
        for change in (identity, lambda b: b['利润明细'].cell(4, 2, '0'),
                       lambda b: b.remove(b['_写入事务']), lambda b: b.create_sheet('未知数据')):
            with self.subTest(change=change):
                raw = mutate_bytes(self.raw, change);plan = preview_bytes(raw, 'xlsx')
                self.assertEqual(plan.source_schema, 'unsupported')
                before = self.ledger.inventory()
                with self.assertRaises(LedgerError):self.apply(raw)
                self.assertEqual(self.ledger.inventory(), before)

    def test_formula_with_and_without_cached_value_is_never_opened_or_evaluated(self):
        for variant in ('formula', 'formula_cached'):
            path = self.root / (variant + '.xlsx');workbook(path, 2, variant=variant)
            with patch('quote_import.adapters.open_book', side_effect=AssertionError('Must preflight formula first')):
                plan = preview_bytes(path.read_bytes(), 'xlsx')
            self.assertEqual(plan.quarantined[0]['code'], 'FORMULA_PRESENT_NO_EVALUATION_OR_CACHE_TRUST')

    def test_corrupt_duplicate_zip_and_xml_entities_are_refused_without_default_zero(self):
        packages = [b'broken zip']
        for name, data, duplicate in [('xl/worksheets/a.xml', b'<!DOCTYPE a [<!ENTITY x "x">]><a/>', False), ('same.xml', b'<a/>', True)]:
            stream = io.BytesIO()
            with ZipFile(stream, 'w', ZIP_DEFLATED) as z:
                z.writestr(name, data)
                if duplicate:
                    with self.assertWarns(UserWarning):z.writestr(name, data)
            packages.append(stream.getvalue())
        for raw in packages:
            plan = preview_bytes(raw, 'xlsx')
            self.assertEqual(plan.source_schema, 'unsupported')
            self.assertIsNone(plan.report()['source_read_active_totals_cents'])

    def test_items_and_legacy_json_import_historical_catalog_without_publication(self):
        self.ledger.publish_prices(str(uuid.uuid4()), self.admin, PriceSnapshot('active', (PriceItem('现价', '99', '33', '1', True),)))
        raw = b'{"items":[{"name":"old","sale":"10","cost":"4","k":"1","single":true}],"export_dir":"unchanged"}'
        result = self.apply(raw, kind='json');self.assertEqual(result['catalog_items'], 1)
        legacy = b'{"old-other":["12","5","1"]}'
        blocked = preview_bytes(legacy, 'json');self.assertEqual(blocked.quarantined[0]['code'], 'LEGACY_SINGLE_POLICY_REQUIRED')
        self.apply(legacy, kind='json', legacy_single_names=['old-other'])
        with self.ledger.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT active_price_id FROM ledger_meta').fetchone()[0], 'active')
            self.assertEqual(c.execute('SELECT count(*) FROM orders').fetchone()[0], 0)

    def test_json_duplicate_invalid_boolean_and_unknown_format_do_not_import(self):
        for raw in (b'{"x":1,"x":2}', b'{"items":[{"name":"x","sale":"1","cost":"0","single":"false"}]}', b'{"unknown":123}'):
            before = self.ledger.inventory()
            with self.assertRaises(LedgerError):self.apply(raw, kind='json')
            self.assertEqual(self.ledger.inventory(), before)

    def test_numeric_raw_expression_and_exact_integer_cents_survive_import(self):
        source = current_book(self.root / 'expressions.xlsx', [(NormalLine('单件', '1/3', name='表达式'),)])
        self.apply(source.read_bytes())
        with self.ledger.connection(readonly=True) as c:
            row = c.execute('SELECT raw_json,income_cents,cost_cents FROM lines').fetchone()
        self.assertEqual(json.loads(row['raw_json'])['q'], '1/3')
        self.assertEqual((row['income_cents'], row['cost_cents']), (333, 133))

    def test_sales_role_cannot_import_or_obtain_a_batch_receipt(self):
        sales = Principal(self.owner, 'sales');plan = preview_bytes(self.raw, 'xlsx')
        with self.assertRaises(Forbidden):
            apply_source(self.ledger, sales, self.owner, self.raw, 'xlsx', expected_review_sha256=plan.review_sha256)
        result = self.apply()
        with self.assertRaises(Forbidden):self.ledger.query_request(result['request_id'], sales)

    def test_mid_batch_failure_rolls_back_prices_orders_lines_receipts_and_batch(self):
        before = self.ledger.inventory()
        def fail(stage, c):
            if stage == 'import_line_inserted':raise OSError('synthetic line failure')
        self.ledger.fault = fail
        with self.assertRaises(OSError):self.apply()
        self.ledger.fault = None
        self.assertEqual(self.ledger.inventory(), before)

    def test_before_commit_failure_is_not_a_partial_import(self):
        before = self.ledger.inventory()
        def fail(stage, c):
            if stage == 'import_before_commit':raise OSError('synthetic precommit failure')
        self.ledger.fault = fail
        with self.assertRaises(OSError):self.apply()
        self.ledger.fault = None
        self.assertEqual(self.ledger.inventory(), before)

    def test_reply_loss_uses_original_batch_query_and_exact_retry_without_duplicates(self):
        def fail(stage, c):
            if stage == 'import_after_commit':raise OSError('lost reply')
        self.ledger.fault = fail
        with self.assertRaises(UnknownCommit) as error:self.apply()
        self.ledger.fault = None;before = self.ledger.inventory()
        original = self.ledger.query_request(error.exception.request_id, self.admin)
        self.assertEqual(self.apply(), original)
        self.assertEqual(self.ledger.inventory(), before)

    def test_two_sqlite_connections_same_source_converge_to_one_batch(self):
        plan = preview_bytes(self.raw, 'xlsx')
        def worker(_):
            return apply_source(Ledger(self.ledger.path), self.admin, self.owner, self.raw, 'xlsx', expected_review_sha256=plan.review_sha256)
        with ThreadPoolExecutor(max_workers=2) as pool:results = list(pool.map(worker, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ledger.inventory()['counts']['import_batches'], 1)

    def test_backup_restore_retains_exact_source_rows_prices_and_original_retry(self):
        original = self.apply();manager = Backups.create(self.root / 'backup', auxiliary=__import__('os').name != 'nt')
        entry = manager.create_backup(self.ledger, kind='maintenance')
        restored = restore_backup(manager.root / entry['backup_id'], self.root / 'restored.sqlite3')
        self.assertEqual(restored.inventory(), self.ledger.inventory())
        with restored.connection(readonly=True) as c:
            self.assertEqual(verify_provenance(c), 1)
            mapping = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
            self.assertEqual(base64.b64decode(mapping['source_base64']), self.raw)
        plan = preview_bytes(self.raw, 'xlsx')
        self.assertEqual(apply_source(restored, self.admin, self.owner, self.raw, 'xlsx', expected_review_sha256=plan.review_sha256), original)

    def test_tampered_provenance_is_refused_against_immutable_batch_receipt(self):
        self.apply()
        with self.ledger.connection() as c:
            mapping = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
            mapping['source_base64'] = base64.b64encode(b'changed').decode()
            c.execute('UPDATE import_batches SET mapping_json=?', (json.dumps(mapping),))
        with self.assertRaises(LedgerError):self.apply()

    def test_review_source_snapshot_is_private_and_original_bytes_are_preserved(self):
        folder = self.root / 'review';folder.mkdir();plan = preview_bytes(self.raw, 'xlsx')
        report = write_review(folder, plan, self.raw)
        self.assertEqual((folder / 'private/source.xlsx').read_bytes(), self.raw)
        self.assertIn('同秒客户', (folder / 'private/plan.json').read_text(encoding='utf-8'))
        self.assertNotIn('同秒客户', json.dumps(report, ensure_ascii=False))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_source_size_and_link_policy_reject_before_reading(self):
        with patch('quote_import.adapters.SOURCE_LIMIT', 1):
            with self.assertRaises(ReviewRequired):read_source(self.source)

    def test_zip_expansion_and_sheet_dimension_limits_reject_before_materializing_cells(self):
        with patch('quote_import.adapters.EXPANDED_LIMIT', 1), patch('quote_import.adapters.open_book', side_effect=AssertionError('opened')):
            plan = preview_bytes(self.raw, 'xlsx')
        self.assertEqual(plan.quarantined[0]['code'], 'ZIP_EXPANSION_LIMIT')
        raw = mutate_bytes(self.raw, lambda b: b['利润明细'].cell(7, 65, '超范围'))
        self.assertEqual(preview_bytes(raw, 'xlsx').quarantined[0]['code'], 'WORKSHEET_DIMENSION_LIMIT')
        with patch.object(Path, 'lstat', return_value=__import__('os').stat_result((0o120777, 0, 0, 0, 0, 0, 0, 0, 0, 0))):
            with self.assertRaises(ReviewRequired):read_source(self.source)

    def test_missing_summary_uses_exact_details_without_inventing_a_footer(self):
        raw = legacy_bytes(self.raw)
        def remove_summary(book):
            for cell in book['利润明细'][4]:cell.value = None
        raw = mutate_bytes(raw, remove_summary)
        plan = preview_bytes(raw, 'xlsx')
        self.assertFalse(plan.quarantined)
        self.assertEqual(plan.report()['source_read_active_totals_cents']['income_cents'], '11100')
        self.assertEqual(self.apply(raw)['created_orders'], 2)

    def test_normalized_quantity_cannot_disagree_with_preserved_raw_expression(self):
        def change(book):
            _, h = table(book['利润明细']);book['利润明细'].cell(7, h['数量'], '5')
        plan = preview_bytes(mutate_bytes(self.raw, change), 'xlsx')
        self.assertEqual(plan.quarantined[0]['code'], 'RAW_AND_NORMALIZED_INPUT_DIFFER')
        self.assertEqual(len(plan.orders), 1)

    def test_unknown_recorded_rule_version_is_quarantined_even_if_amounts_match(self):
        def change(book):
            history = book['订单价格快照']
            for i in range(2, history.max_row + 1):history.cell(i, 5, 'future-unverified-rule')
        plan = preview_bytes(mutate_bytes(self.raw, change), 'xlsx')
        self.assertEqual(len(plan.orders), 0)
        self.assertEqual(len(plan.quarantined), 2)
        self.assertTrue(all(q['code'] == 'HISTORICAL_RULE_VERSION_UNSUPPORTED' for q in plan.quarantined))

    def test_discount_coefficient_and_subtotal_must_match_core_order_sequence(self):
        for field, value, code in [('折扣系数', '.95', 'DISCOUNT_COEFFICIENT_DIFFERS'),
                                   ('折前销售额', '41.00', 'DISCOUNT_SUBTOTAL_DIFFERS')]:
            with self.subTest(field=field):
                def change(book):
                    _, h = table(book['利润明细']);book['利润明细'].cell(8, h[field], value)
                plan = preview_bytes(mutate_bytes(self.raw, change), 'xlsx')
                self.assertEqual(plan.quarantined[0]['code'], code)
                self.assertEqual(len(plan.orders), 1)

    def test_identified_note_reimport_reuses_original_note_id(self):
        append_note_and_void(self.source);raw = self.source.read_bytes();self.apply(raw)
        changed = mutate_bytes(raw, lambda b: setattr(b.properties, 'title', '元数据改变'))
        report = self.apply(changed)
        self.assertEqual(report['created_orders'], 0)
        self.assertEqual(self.ledger.inventory()['counts']['notes'], 1)
        self.assertTrue(any('note_id' in r for r in report['row_map']))


if __name__ == '__main__':unittest.main()
