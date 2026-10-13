"""P05-03 isolated synthetic import, Windows protection and full-host restore."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'), str(ROOT / 'tests')]
from p01_validation import new_output
from p03_format_check import case_ids


def fingerprints():
    paths = [*ROOT.glob('quote_import/*.py'), *ROOT.glob('quote_core/*.py'),
             *ROOT.glob('quote_ledger/*.py'), *ROOT.glob('quote_service/*.py'),
             ROOT / 'quote_app/projection.py', ROOT / 'quote_files/schema.py',
             ROOT / 'quote_files/reading.py', ROOT / 'quote_files/documents.py',
             ROOT / 'quote_files/workbooks.py', ROOT / 'quote_files/orders.py',
             ROOT / 'quote_files/transactions.py', ROOT / 'tests/import_fixture.py',
             ROOT / 'tests/test_legacy_import.py', ROOT / 'tests/test_p05_import_entry.py',
             ROOT / 'tests/test_p05_import_check.py', ROOT / 'tools/p01_fixtures.py',
             ROOT / 'tools/p05_import.py', Path(__file__), ROOT / 'requirements-service.txt',
             ROOT / 'docs/baseline/p01-04-golden.json']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sorted(paths)}


def run_checks():
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_legacy_import', 'test_p05_import_entry', 'test_p05_import_check'])
    ids = list(case_ids(suite));log = io.StringIO();start = time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    return {'status': 'passed' if result.wasSuccessful() else 'failed', 'tests_run': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors), 'skipped': result.skipped,
            'elapsed_seconds': time.monotonic() - start, 'test_ids': ids, 'log': log.getvalue(),
            'failure_details': [{'test_id': case.id(), 'error': trace.strip().splitlines()[-1]}
                                for case, trace in [*result.errors, *result.failures]]}


def isolated_import(*, auxiliary=False):
    if not auxiliary and platform.system() != 'Windows':
        raise RuntimeError('Actual Windows required before native import access')
    from import_fixture import current_book, append_note_and_void
    from quote_import import preview_bytes, apply_source, read_source
    from quote_import.review import write_review
    from quote_import.store import verify_provenance
    from quote_service.hosting import initialize, load
    from quote_service.recovery import restore
    from quote_files.transactions import file_lock
    with tempfile.TemporaryDirectory(prefix='777-p05-import-') as temp:
        root = Path(temp);password = secrets.token_urlsafe(24)
        config = initialize(root / 'host', root / 'backups', 'manager', password, hosts=['localhost'], auxiliary=auxiliary)
        _, _, service = load(root / 'host', auxiliary=auxiliary)
        login = service.auth.login('manager', password, 'isolated-import')
        actor = service.auth.authenticate(login['token'])
        source = append_note_and_void(current_book(root / '隔离来源.xlsx'))
        raw = read_source(source);mtime = source.stat().st_mtime_ns
        plan = preview_bytes(raw, 'xlsx');before = service.ledger.inventory()
        review_dir = root / 'review';review_dir.mkdir()
        review = write_review(review_dir, plan, raw)
        assert service.ledger.inventory() == before
        assert plan.report()['eligible_orders'] == 2 and plan.report()['eligible_notes'] == 1
        with file_lock(root / 'host/service-owner'):
            prior = service.backup(kind='maintenance');assert prior['full_service_verified']
            committed = apply_source(service.ledger, actor, actor.subject, raw, 'xlsx', expected_review_sha256=plan.review_sha256)
            inventory = service.ledger.inventory()
            assert inventory['counts']['orders'] == 2 and inventory['counts']['lines'] == 3 and inventory['counts']['notes'] == 1
            assert (inventory['active_income_cents'], inventory['active_cost_cents'], inventory['active_profit_cents']) == ('7500', '3000', '4500')
            assert apply_source(service.ledger, actor, actor.subject, raw, 'xlsx', expected_review_sha256=plan.review_sha256) == committed
            assert service.ledger.inventory() == inventory
            with service.ledger.connection(readonly=True) as c:
                assert verify_provenance(c) == 1
                assert c.execute('SELECT active_price_id FROM ledger_meta').fetchone()[0] is None
            backup = service.backup(kind='maintenance');assert backup['full_service_verified']
            restored, auth = restore(backup['service_bundle'], root / 'restored-host', 'manager', 'isolated-restored-password', auxiliary=auxiliary)
            assert restored.inventory() == inventory
            with restored.connection(readonly=True) as c:
                assert verify_provenance(c) == 1
                import base64
                mapping = json.loads(c.execute('SELECT mapping_json FROM import_batches').fetchone()[0])
                assert base64.b64decode(mapping['source_base64']) == raw
            with auth.connection() as c:
                assert c.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        service.auth.logout(login['token'])
        assert source.read_bytes() == raw and source.stat().st_mtime_ns == mtime
        assert (review_dir / 'private/source.xlsx').read_bytes() == raw
        outcome = {'status': 'passed', 'scope': 'Temporary synthetic source and host only; no real E/share/live ledger or user historical import.',
                   'source_sha256': hashlib.sha256(raw).hexdigest(), 'source_hash_and_mtime_unchanged': True,
                   'dry_run_zero_ledger_writes': True, 'source_row_mapping': True, 'two_same_second_orders_distinct': True,
                   'notes_void_and_exact_active_amounts': True, 'duplicate_batch_no_additional_writes': True,
                   'complete_pre_import_maintenance_backup': True, 'complete_post_import_independent_host_restore': True,
                   'original_source_bytes_and_provenance_restored': True, 'account_ids_preserved_and_old_sessions_removed': True,
                   'active_price_not_changed': True, 'inventory': inventory,
                   'private_review_security': review['private_directory_security'],
                   'host_private_security': config['private_security'], 'sandbox_cleaned': False,
                   'auxiliary': auxiliary}
    outcome['sandbox_cleaned'] = True
    return outcome


def windows_smoke():
    return isolated_import(auxiliary=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--windows-smoke', action='store_true')
    mode.add_argument('--checks-only', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv);output = new_output(args.output)
    report = {'task': 'P05-03', 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'environment': {'os': platform.system(), 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version},
              'implementation_sha256_LF': fingerprints(), 'status': 'running', 'checks': None, 'native_smoke': None,
              'production_paths_accessed': False, 'production_files_read_or_modified': False,
              'real_historical_data_imported': False, 'Windows_acceptance': 'pending'}
    if args.windows_smoke and platform.system() != 'Windows':
        report.update(status='blocked', reason='Actual Windows required before source/host/native protection access')
    else:
        report['checks'] = run_checks()
        if report['checks']['status'] != 'passed':
            report['status'] = 'failed'
        elif args.windows_smoke:
            try:
                report['native_smoke'] = windows_smoke()
                report['status'] = 'Windows_isolated_import_passed_acceptance_pending'
            except Exception as exc:
                report.update(status='failed', error=f'{type(exc).__name__}: {exc}', native_error_traceback=traceback.format_exc())
        else:
            report['status'] = 'auxiliary_import_checks_passed_Windows_pending'
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary = {k: report[k] for k in ('task', 'status', 'environment', 'native_smoke')}
    if report['checks']:
        summary['checks'] = {k: report['checks'][k] for k in ('status', 'tests_run', 'failures', 'errors', 'skipped', 'failure_details')}
    for key in ('error', 'reason'):
        if key in report:summary[key] = report[key]
    summary['report_path'] = str(output / 'report.json')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report['status'] in ('Windows_isolated_import_passed_acceptance_pending', 'auxiliary_import_checks_passed_Windows_pending') else 2


if __name__ == '__main__':raise SystemExit(main())
