"""P03-01 diagnostics: synthetic Windows tests/GUI or explicit read-only receipt lookup."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'), str(ROOT / 'tests')]
import baseline_check
import p02_gui_check as gui
from quote_files.transactions import query_request
from quote_files.workbooks import inspect_receipt, open_book, receipts, table


def transaction_gui_smoke(manager, sales, sandbox):
    checks = shared_directory_smoke(manager, sales, sandbox)
    path = sales._excel_pending['path']
    rid = sales._excel_pending['request'].request_id
    before = Path(path).read_bytes()
    assert sales.export_to_excel() == path
    assert sales.last_file_transaction.already_committed
    assert Path(path).read_bytes() == before
    manager.add_calc_row('母版新单', 'P02面积', False)
    manager.calculate(notify=False)
    manager.confirm_current_prices()
    assert manager.calc_export_button.invoke() == path
    manager.open_excel_path(path)
    manager.excel_view_tree.selection_set('row_7')
    manager.excel_remark_text.insert('1.0', '=1+1')
    assert manager.save_current_excel_remark()
    manager.excel_view_tree.selection_set('row_7')
    with patch('tkinter.messagebox.askyesno', return_value=True):
        assert manager.delete_current_excel_row()
    book = open_book(Path(path).read_bytes())
    try:
        ws = book['利润明细']
        _, h = table(ws)
        assert ws.max_row == 10
        assert ws.cell(7, h['记录状态']).value == 'void'
        assert ws.cell(9, h['记录状态']).value == 'active'
        assert ws.cell(8, h['备注']).value == '=1+1'
        assert ws.cell(8, h['备注']).data_type == 's'
        assert ws.cell(4, 2).value == '12.00' and ws.cell(4, 4).value == '4.00'
        assert len(receipts(book)) == 4
        assert rid in receipts(book)
    finally:
        book.close()
    assert '_写入事务' not in manager.excel_sheet_combo.cget('values')
    checks.update(repeated_click_single_receipt='passed', manager_append_remark_and_soft_void='passed',
                  preserved_rows_and_active_summary='passed', hidden_transaction_sheet='passed')
    return checks


def windows_tests():
    suite = unittest.TestSuite()
    for module in ('test_file_transactions', 'test_workbook_transactions'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
    def ids(suite):
        for case in suite:
            if isinstance(case, unittest.TestSuite):
                yield from ids(case)
            else:
                yield case.id()
    case_ids = list(ids(suite))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {'status': 'passed' if result.wasSuccessful() else 'failed', 'tests_run': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors), 'skipped': result.skipped,
            'test_ids': case_ids, 'log': stream.getvalue(), 'scope': 'Synthetic local files and native process locks; no production share'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke', action='store_true')
    mode.add_argument('--gui-smoke', action='store_true')
    mode.add_argument('--launch-pair', action='store_true')
    mode.add_argument('--request-status', type=Path, metavar='FILE')
    parser.add_argument('--request-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = {'task': 'P03-01', 'environment': {'os': platform.system(), 'python': platform.python_version()},
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'implementation_sha256_LF': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for p in sorted([*ROOT.glob('quote_files/*.py'), *ROOT.glob('quote_app/*.py'), *ROOT.glob('报价*.py'), Path(__file__)])},
              'production_paths_accessed': False, 'windows_shared_acceptance': 'pending'}
    if args.request_status:
        if not args.request_id:
            parser.error('--request-status requires --request-id UUID')
        if args.output and args.output.resolve() == args.request_status.resolve():
            parser.error('report must not overwrite the inspected file')
        report['scope'] = 'Explicit file plus adjacent recovery receipt, read-only; no restore or lock deletion'
        try:
            inspector = (lambda *_: None) if args.request_status.suffix.lower() == '.json' else inspect_receipt
            report['request'] = query_request(args.request_status, args.request_id, inspector)
            report['status'] = 'queried'
            report['production_paths_accessed'] = 'explicit_selected_file_only'
        except Exception as exc:
            report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    elif platform.system() != 'Windows':
        report.update(status='blocked', reason='Windows checks only; run unittest separately for auxiliary checks')
    else:
        report['scope'] = 'Temporary synthetic local files only; not two physical SMB clients or network interruption acceptance'
        try:
            if args.windows_smoke:
                report['checks'] = windows_tests()
                report['status'] = report['checks']['status']
            elif args.launch_pair:
                report['gui'] = gui.run_pair(manual=True)
                report['status'] = 'failed' if report['gui']['status'] == 'failed' else 'manual_observation_pending'
            else:
                with patch.object(gui, 'shared_directory_smoke', side_effect=transaction_gui_smoke):
                    # Keep the original helper reachable without recursive patching.
                    report['gui'] = gui.run_pair()
                report['status'] = report['gui']['status']
        except Exception as exc:
            report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    baseline_check.emit(report, args.output)
    return 2 if report['status'] == 'blocked' else int(report['status'] == 'failed')


shared_directory_smoke = gui.shared_directory_smoke
# The saved reference remains available while the GUI helper is temporarily patched.

if __name__ == '__main__':
    raise SystemExit(main())
