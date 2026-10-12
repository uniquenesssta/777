"""Measurement boundaries and real synthetic read counts, not Windows claims."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import openpyxl
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.worksheet import Worksheet
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

import p01_fixtures as fixtures
from p04_metrics import Heartbeat, distribution, healthy_heartbeat, input_hashes, instrumentation
import p04_performance_check as perf
from quote_files.documents import parse_document


class PerformanceMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='777-p04-measurement-test-')
        self.root = Path(self.temp.name)
        codec = patch('io.text_encoding', side_effect=lambda encoding, stacklevel=2: 'gbk' if encoding in (None, 'locale') else encoding)
        codec.start();self.addCleanup(codec.stop)
    def tearDown(self):self.temp.cleanup()

    def test_p95_cannot_hide_single_563ms_maximum(self):
        clock = 0.;heart = Heartbeat();heart.start(clock)
        for gap in [50.] * 39 + [563.]:
            clock += gap / 1000;heart.pulse(clock)
        data = heart.finish(clock)
        self.assertLess(data['p95_gap_ms'], 100)
        self.assertAlmostEqual(data['max_gap_ms'], 563.)
        self.assertEqual(data['over_500_ms'], 1)
        self.assertEqual(data['status'], 'failed')
        self.assertFalse(healthy_heartbeat(data))

    def test_phase_boundary_includes_work_before_first_callback_and_rejects_short_sampling(self):
        heart = Heartbeat();heart.start(0.)
        data = heart.finish(.8)
        self.assertEqual(data['gaps_ms'], [800.])
        self.assertEqual(data['status'], 'insufficient_samples')
        self.assertFalse(healthy_heartbeat(data))

    def test_stage_reset_excludes_preparation_but_preserves_every_stage_gap(self):
        heart = Heartbeat();heart.pulse(100.)
        heart.start(101.)
        for i in range(1, 22):heart.pulse(101. + i * .05)
        first = heart.finish(102.1)
        self.assertTrue(healthy_heartbeat(first))
        heart.pulse(200.)  # no active phase: preprocessing is not UI work
        heart.start(201.)
        data = heart.finish(201.7)
        self.assertAlmostEqual(data['max_gap_ms'], 700.)
        self.assertGreater(len(first['gaps_ms']), 20)

    def test_summary_recomputes_raw_gaps_instead_of_trusting_passed_flag(self):
        data = {'samples': 21, 'gaps_ms': [50.] * 20 + [563.], 'p95_gap_ms': 50., 'max_gap_ms': 50., 'status': 'passed'}
        self.assertFalse(healthy_heartbeat(data))
        data['max_gap_ms'] = 563.
        self.assertFalse(healthy_heartbeat(data))
        self.assertEqual(distribution([]), {'samples': 0, 'p50': None, 'p95': None, 'max': None})

    def test_negative_and_nonfinite_clock_samples_are_errors(self):
        for now in (-1., float('nan'), float('inf')):
            heart = Heartbeat();heart.start(0.)
            with self.assertRaises(ValueError):heart.pulse(now)

    def test_real_current_decode_is_one_open_one_xml_and_one_source_iteration(self):
        path = self.root / '合成.xlsx';fixtures.workbook(path, 3)
        with instrumentation() as counts:doc = parse_document(path.read_bytes())
        self.assertEqual(doc.result.detail_count, 3)
        self.assertEqual(counts['workbook_opens'], 1)
        self.assertEqual(counts['worksheet_xml_source_opens'], 1)
        self.assertEqual(counts['iter_rows_calls'], 1)
        self.assertEqual(counts['yielded_rows'], 9)

    def test_readonly_cell_reopens_are_observed_and_all_hooks_restore_after_error(self):
        path = self.root / '合成.xlsx';fixtures.workbook(path, 3)
        before = (openpyxl.load_workbook, Worksheet.iter_rows, ReadOnlyWorksheet.iter_rows, ZipFile.open)
        with self.assertRaisesRegex(RuntimeError, 'diagnostic'):
            with instrumentation() as counts:
                book = openpyxl.load_workbook(path, read_only=True)
                try:
                    for row in range(7, 10):book.active.cell(row, 5).value
                    self.assertEqual(counts['workbook_opens'], 1)
                    self.assertGreaterEqual(counts['worksheet_xml_source_opens'], 3)
                    raise RuntimeError('diagnostic')
                finally:book.close()
        self.assertEqual(before, (openpyxl.load_workbook, Worksheet.iter_rows, ReadOnlyWorksheet.iter_rows, ZipFile.open))

    def test_fixture_bytes_are_identical_for_manager_sales_and_rounds_are_not_regenerated(self):
        cases = perf.make_inputs(self.root, ['small'])
        manager = next(c for c in cases if c['id'] == 'manager-rows-100')
        sales = next(c for c in cases if c['id'] == 'sales-rows-100')
        self.assertEqual(manager['input_sha256'], sales['input_sha256'])
        before = input_hashes(self.root / manager['id'] / 'inputs')
        for _ in range(2):
            case, folder = perf.get_case(self.root, manager['id'])
            self.assertEqual(case, manager)
            self.assertEqual(input_hashes(folder / 'inputs'), before)

    def test_changed_synthetic_inputs_refuse_measurement(self):
        cases = perf.make_inputs(self.root, ['small']);case = cases[0]
        path = next((self.root / case['id'] / 'inputs').glob('*.xlsx'))
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC_INPUT_CHANGED'):perf.get_case(self.root, case['id'])

    def test_actual_current_small_read_counts_and_exact_amounts_with_fresh_round_reset(self):
        cases = perf.make_inputs(self.root, ['small'])
        for case in (cases[0], cases[2]):
            result = perf.worker(self.root, case['id'], 'current')
            cold, warm = result['measurements']
            self.assertEqual(cold['counts']['workbook_opens'], case['files'])
            self.assertEqual(warm['counts'].get('workbook_opens', 0), 0)
            self.assertEqual(cold['observed']['income_cents'], case['income_cents'])
            self.assertEqual(cold['observed']['cost_cents'], case['cost_cents'])
            self.assertTrue(result['inputs_unchanged'])
            ns = perf.prepare_current(self.root / case['id'], case['role'])
            shared = json.loads((self.root / case['id'] / 'storage.json').read_text(encoding='utf-8'))
            self.assertEqual(shared['export_dir'], 'reports')

    def test_actual_original_matched_small_preserves_known_cost_defect_and_five_n_reads(self):
        case = perf.make_inputs(self.root, ['small'])[0]
        result = perf.worker(self.root, case['id'], 'original')
        for row in result['measurements']:
            self.assertEqual(row['counts']['workbook_opens'], 5 * case['files'])
            self.assertFalse(row['observed']['correct'])
            self.assertIn('known_baseline_issue', row['observed'])
        self.assertTrue(result['inputs_unchanged'])

    def test_non_windows_gui_block_precedes_all_input_and_widget_access(self):
        with patch.object(perf.platform, 'system', return_value='Linux'), patch.object(perf, 'get_case', side_effect=AssertionError('input accessed')):
            with self.assertRaisesRegex(ValueError, 'WINDOWS_GUI_ONLY'):perf.worker(self.root, 'ignored', 'current', native=True)
        with patch.object(perf.platform, 'system', return_value='Linux'):
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_WINDOWS_UNC'):perf.shared_parent('\\\\synthetic\\share')

    def test_timeout_is_unavailable_sample_and_cannot_be_matched_baseline(self):
        case = perf.make_inputs(self.root, ['small'])[0]
        with patch.object(perf.subprocess, 'run', side_effect=perf.subprocess.TimeoutExpired('worker', 5)):
            result = perf.launch_worker(self.root, case, 'original', False, 5)
        self.assertEqual(result['status'], 'timeout')
        self.assertNotIn('measurements', result)
        self.assertFalse(perf.legacy_complete([result], [case], 5, ['small']))

    def test_missing_native_phases_or_headless_samples_cannot_pass_windows_performance(self):
        case = perf.make_inputs(self.root, ['small'])[0]
        result = perf.worker(self.root, case['id'], 'current')
        runs = []
        for _ in range(5):
            for index in range(9):runs.append({**deepcopy(result), 'case_id': str(index)})
        cases = [{**case, 'id': str(index)} for index in range(9)]
        auxiliary = perf.summarize(runs, cases, 5, False)
        self.assertTrue(auxiliary['current_correctness_and_read_counts_passed'])
        self.assertFalse(auxiliary['Windows_healthy_performance_passed'])
        native = perf.summarize(runs, cases, 5, True)
        self.assertFalse(native['Windows_healthy_performance_passed'])
        self.assertFalse(native['current_correctness_and_read_counts_passed'])

    def test_gui_sequence_preflight_uses_real_background_adapters_and_all_phase_gates(self):
        # Tcl/replacement controls validate the diagnostic workflow only. No
        # Tk widgets, Windows heartbeat/DPI or native performance acceptance.
        from test_application_integration import application
        from test_background_io import asynchronous
        from test_pagination_images import page_controls
        from quote_app.background import BackgroundApplicationMixin
        for role in ('manager', 'sales'):
            with self.subTest(role=role), application(role) as (app, folder, ns, _), asynchronous(app):
                inputs = folder / 'inputs';inputs.mkdir();fixtures.workbook(inputs / 'synthetic.xlsx', 401)
                case = {'role': role, 'files': 1, 'detail_rows_per_file': 401,
                        'income_cents': 401000, 'cost_cents': 160400, 'profit_cents': 240600}
                page_controls(app)
                app.excel_next_button.invoke = lambda a=app: a.change_excel_page(1)
                app.excel_filter_button = Mock();app.excel_filter_button.invoke = app.filter_excel_view
                app.notebook = Mock();app.notebook.tabs.return_value = ('excel',);app.notebook.tab.return_value = 'Excel记录'
                alive = [True]
                window = app.root
                original_tcl = window.tk
                class TclProxy:
                    def call(self, *args):
                        if args == ('tk', 'scaling'):return 1.0
                        return original_tcl.call(*args)
                    def __getattr__(self, name):return getattr(original_tcl, name)
                window.tk = TclProxy()
                def loop():
                    deadline = time.monotonic() + 15
                    while alive[0] and time.monotonic() < deadline:
                        window.tk.eval('update');time.sleep(.002)
                    if alive[0]:raise TimeoutError('auxiliary workflow did not finish')
                window.mainloop = loop;window.quit = lambda: alive.__setitem__(0, False)
                import tkinter as tk
                window.attributes = Mock();window.protocol = Mock()
                window.destroy = Mock(side_effect=[None, tk.TclError('root already destroyed')])
                # Exercise actual scheduled poll callbacks rather than the
                # test fixture's manual pump wrapper.
                app._poll_io = BackgroundApplicationMixin._poll_io.__get__(app)
                class Factory:
                    def __new__(cls, _):return app
                with patch('tkinter.Tk', return_value=window), patch.object(perf.gui, 'live_sandbox_type', return_value=Factory):
                    measured, _ = perf.gui_measurements(ns, folder, case, True)
                window.attributes.assert_called_once_with('-disabled', True)
                self.assertEqual(window.destroy.call_count, 2)
                # The shared Tcl fixture also pumps its closed runtime during
                # teardown. Its extra destroy is outside this diagnostic.
                window.destroy.side_effect = None
                self.assertEqual([m['phase'] for m in measured], ['first_refresh', 'warm_refresh', 'open_view', 'all_pages', 'filter_last_detail'])
                self.assertEqual(measured[0]['counts']['workbook_opens'], 1)
                self.assertEqual(measured[1]['counts'].get('workbook_opens', 0), 0)
                self.assertEqual(measured[3]['observed']['visible_rows'], 407 if role == 'manager' else 401)
                self.assertEqual(measured[3]['observed']['pages'], 3)
                self.assertEqual(measured[4]['observed']['source_row'], 407)

    def test_cli_off_windows_reports_blocked_without_probing_shared_root(self):
        with patch.object(perf, 'run_checks', return_value={'status': 'passed', 'tests_run': 0}), \
             patch.object(perf.original, 'new_output', return_value=self.root), \
             patch.object(perf.platform, 'system', return_value='Linux'), \
             patch.object(perf, 'shared_parent', side_effect=AssertionError('share accessed')), \
             patch('sys.stdout', new=io.StringIO()):
            code = perf.main(['--gui-heartbeat', '--shared-root', '\\\\synthetic\\share', '--output', 'ignored'])
        report = json.loads((self.root / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'blocked')
        self.assertFalse(report['production_paths_accessed'])
        self.assertEqual(report['storages'], [])

    def test_preparation_failure_emits_failed_report_instead_of_successful_checks_snapshot(self):
        with patch.object(perf, 'run_checks', return_value={'status': 'passed', 'tests_run': 0}), \
             patch.object(perf.original, 'new_output', return_value=self.root), \
             patch.object(perf, 'make_inputs', side_effect=PermissionError('synthetic preparation refused')), \
             patch('sys.stdout', new=io.StringIO()):
            code = perf.main(['--auxiliary', '--output', 'ignored'])
        report = json.loads((self.root / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('PermissionError', report['error'])
        self.assertEqual(report['storages'], [])


if __name__ == '__main__':unittest.main()
