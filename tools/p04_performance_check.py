"""P04-04 matched synthetic cold/warm measurements; optional actual Windows Tk.

Writes only a new reports directory and exclusive temporary input directories.
An explicit --shared-root permits a temporary child on that UNC share. Existing
share workbooks/settings are never scanned. Workers only read synthetic inputs;
timeouts terminate read-only diagnostic processes, never application writers.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'), str(ROOT / 'tests')]
import baseline_check
import p01_fixtures as fixtures
import p01_validation as original
import p02_gui_check as gui
from p03_format_check import case_ids
from p04_metrics import Heartbeat, distribution, healthy_heartbeat, input_hashes, instrumentation

SIZES = {'small': (100, 10), 'medium': (1000, 100), 'large': (10000, 1000)}


def limits():
    accepted = json.loads((ROOT / 'docs/baseline/p01-acceptance.json').read_text(encoding='utf-8'))['performance']
    return {'profile': accepted['profile_id'], 'heartbeat_p95_ms': accepted['healthy_UI_heartbeat_p95_gap_ms'],
            'heartbeat_max_ms': accepted['healthy_UI_heartbeat_max_gap_ms'], 'minimum_rounds': 5}


def run_checks():
    suite = unittest.defaultTestLoader.loadTestsFromName('test_performance_measurement')
    ids, log, started = list(case_ids(suite)), io.StringIO(), time.monotonic()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    return {'status': 'passed' if result.wasSuccessful() else 'failed', 'tests_run': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors), 'skipped': result.skipped,
            'test_ids': ids, 'log': log.getvalue(), 'elapsed_seconds': time.monotonic() - started}


def make_inputs(root, sizes):
    """P01 generator/content, shared once across implementations and rounds."""
    root = Path(root)
    cases = []
    template = root / 'template.xlsx'
    fixtures.workbook(template, 1)
    for size in sizes:
        rows, files = SIZES[size]
        row_template = root / f'rows-{rows}.xlsx'
        fixtures.workbook(row_template, rows)
        for role, kind, count in [('manager', 'files', files), ('manager', 'rows', rows), ('sales', 'rows', rows)]:
            case_id = f'{role}-{kind}-{count}'
            folder = root / case_id / 'inputs'
            folder.mkdir(parents=True)
            for index in range(count if kind == 'files' else 1):
                shutil.copyfile(template if kind == 'files' else row_template, folder / f'synthetic_{index:04d}.xlsx')
            detail_rows = count
            case = {'id': case_id, 'size': size, 'role': role, 'kind': kind,
                    'files': count if kind == 'files' else 1, 'detail_rows_per_file': 1 if kind == 'files' else count,
                    'income_cents': detail_rows * 1000, 'cost_cents': detail_rows * 400, 'profit_cents': detail_rows * 600,
                    'input_sha256': input_hashes(folder), 'legacy_p01_workload': kind == 'files' or role == 'sales'}
            cases.append(case)
            fixtures.write_json(root / case_id / 'case.json', case)
    fixtures.write_json(root / 'p04-run.json', {'task': 'P04-04', 'run_id': str(uuid.uuid4()), 'cases': cases,
        'origin': 'P01 synthetic generator, same immutable workbook bytes for all versions/rounds within this run',
        'cold_scope': 'Fresh process/application cache, not physical disk/SMB server cache; input hashing itself reads bytes.'})
    return cases


def get_case(root, case_id):
    root = Path(root).resolve()
    marker = json.loads((root / 'p04-run.json').read_text(encoding='utf-8'))
    if marker['task'] != 'P04-04' or str(uuid.UUID(marker['run_id'])) != marker['run_id']:
        raise ValueError('NOT_AN_ISOLATED_PERFORMANCE_RUN')
    case = next(c for c in marker['cases'] if c['id'] == case_id)
    if case_id != f"{case['role']}-{case['kind']}-{case['files'] if case['kind']=='files' else case['detail_rows_per_file']}":
        raise ValueError('INVALID_CASE_ID')
    folder = root / case_id
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)() or not folder.resolve().is_relative_to(root):
        raise ValueError('CASE_ESCAPES_TEMPORARY_RUN')
    if input_hashes(folder / 'inputs') != case['input_sha256']:
        raise ValueError('SYNTHETIC_INPUT_CHANGED')
    return case, folder


def prepare_current(folder, role):
    ns, _ = gui.load_namespace(ROOT, role, folder)
    from quote_files.settings import encode_settings
    # Every fresh process starts with an empty report folder, including later
    # rounds after an earlier worker published the synthetic input directory.
    (folder / 'storage.json').write_bytes(encode_settings({'schema': '777-shared-v1',
        'price_file': 'config.json', 'export_dir': 'reports', 'screenshot_dir': 'screenshots'}, 'shared'))
    return ns


def point_at_inputs(app, folder, current):
    if current:
        from quote_files.settings import encode_settings
        (folder / 'storage.json').write_bytes(encode_settings({'schema': '777-shared-v1',
            'price_file': 'config.json', 'export_dir': 'inputs', 'screenshot_dir': 'screenshots'}, 'shared'))
        if not app.observe_storage():
            raise ValueError('ISOLATED_SHARED_SETTINGS_NOT_LOADED')
        app._ledger_cache.clear()
    else:
        app.report_dir = str(folder / 'inputs')


def observations(app, case, current, scan=None):
    if current:
        scan = scan if scan is not None else app.excel_read_results
        good = [r for r, _ in scan.values() if r.status == 'ok']
        observed = {'files': len(scan), 'valid_files': len(good), 'detail_rows': sum(r.detail_count for r in good),
            'income_cents': sum(r.totals.income_cents for r in good),
            'cost_cents': sum(r.totals.cost_cents for r in good), 'profit_cents': sum(r.totals.profit_cents for r in good)}
        expected = {k: case[k] for k in ('files', 'income_cents', 'cost_cents', 'profit_cents')}
        expected.update(valid_files=case['files'], detail_rows=case['files'] * case['detail_rows_per_file'])
        if observed != expected:
            raise AssertionError(f'CURRENT_RESULT_MISMATCH: {observed} != {expected}')
        aggregate = getattr(scan, 'aggregate', {})
        if any(aggregate.get(k) != observed[k] for k in ('valid_files', 'income_cents', 'cost_cents', 'profit_cents')) or aggregate.get('errors') != 0 or aggregate.get('unsupported') != 0:
            raise AssertionError('DIRECTORY_AGGREGATE_MISMATCH')
        if hasattr(app, 'excel_file_tree'):
            if len(app.excel_file_tree.get_children()) != case['files']:
                raise AssertionError('INCOMPLETE_FILE_LIST')
            if case['role'] == 'manager':
                from quote_core.numbers import money_text
                displayed = {k: getattr(app, 'excel_total_' + k).get() for k in ('income', 'cost', 'profit')}
                if displayed != {k: money_text(case[k + '_cents']) for k in displayed}:
                    raise AssertionError('DISPLAYED_TOTAL_MISMATCH')
                observed['displayed_totals'] = displayed
        observed['correct'] = True
        return observed
    tree = app.excel_file_tree
    values = [tree.item(item, 'values') for item in tree.get_children()]
    observed = {'files': len(values), 'correct': len(values) == case['files']}
    if case['role'] == 'sales':
        observed['detail_rows'] = sum(int(value[2]) for value in values)
        observed['correct'] &= observed['detail_rows'] == case['files'] * case['detail_rows_per_file']
    else:
        from decimal import Decimal
        observed['displayed_totals'] = {k: getattr(app, 'excel_total_' + k).get() for k in ('income', 'cost', 'profit')}
        observed['correct'] &= all(Decimal(v) * 100 == case[k + '_cents'] for k, v in observed['displayed_totals'].items())
        if not observed['correct']:
            observed['known_baseline_issue'] = 'Original summary header overwrites cost (P01 A09); retained unchanged, no financial equivalence claim.'
    return observed


def headless_app(namespace, folder, current):
    if not current:
        audit = original.module(ROOT / 'docs/audit/reproduce.py')
        app = audit.instance(namespace, folder / 'inputs')
        app.excel_file_tree = original.CaptureTree()
        for key in ('count', 'income', 'cost', 'profit', 'margin'):
            setattr(app, 'excel_total_' + key, audit.Var())
        return app
    from quote_app.background import Value
    from quote_files.cache import LedgerCache
    class Headless(namespace['PriceCalculator']):
        def _new_text_var(self, value):return Value(value)
        def set_feedback(self, *_args, **_kwargs):pass
    app = Headless.__new__(Headless)
    app._io_runtime, app._ledger_cache = None, LedgerCache()
    app.export_dir_var = Value('')
    app._initialize_connection_fields()
    app._restore_connection()
    point_at_inputs(app, folder, True)
    return app


class Context:
    def check(self):pass


def measure_headless(app, namespace, case, current, condition):
    from quote_app.background import perform
    before = app._ledger_cache.metrics() if current else {}
    with instrumentation(None if current else namespace) as counts:
        tracemalloc.start()
        started = time.perf_counter()
        try:
            if current:
                scan = perform(app, 'scan', None, Context())
                if case['role'] == 'manager':
                    scan = perform(app, 'scan', None, Context())
            else:
                original.refresh(app, case['role'])
                scan = None
            seconds = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    after = app._ledger_cache.metrics() if current else {}
    return {'phase': condition, 'seconds': seconds, 'python_allocation_peak_bytes': peak,
            'counts': dict(counts), 'cache_delta': {k: after.get(k, 0) - before.get(k, 0)
                for k in ('source_reads', 'source_bytes', 'workbook_opens', 'formula_cache_opens', 'weak_hash_probes')},
            'cache_after': after, 'observed': observations(app, case, current, scan),
            'heartbeat': 'not_measured: control-free background model; auxiliary only'}


def gui_measurements(namespace, folder, case, current):
    import tkinter as tk
    window = tk.Tk()
    # Diagnostic read-only windows: programmatic read controls still run, but
    # user input cannot start a save while the parent owns a read-only timeout.
    window.attributes('-disabled', True)
    errors = gui.track_callback_errors(window)
    cls = gui.live_sandbox_type(namespace, folder) if current else baseline_check.sandbox_application_type(namespace, folder)
    if current:
        class Live(cls):background_io_enabled = True
        cls = Live
    app = None
    startup_jobs, feedback_errors = set(), []
    measurements, heartbeat_jobs = [], []
    accepted = limits()
    heart = Heartbeat(accepted['heartbeat_p95_ms'], accepted['heartbeat_max_ms'])
    def pulse():
        heart.pulse(time.perf_counter())
        heartbeat_jobs[:] = [window.after(50, pulse)]
    error, error_cause, waiting, active_phase = None, None, None, 'startup'
    active_context = None
    def completed(task):
        if not task or not hasattr(task, 'number'):
            raise AssertionError('READ_REQUEST_NOT_QUEUED')
        def delivered():
            if feedback_errors:
                raise RuntimeError('APPLICATION_READ_FAILED: ' + feedback_errors[-1])
            return task.number not in app._io_callbacks
        return delivered
    def phase(name, action, *, observed=None):
        nonlocal active_phase
        active_phase = name
        feedback_errors.clear()
        print('P04_PHASE ' + json.dumps({'phase': name, 'state': 'started'}), file=sys.stderr, flush=True)
        before = app._ledger_cache.metrics() if current else {}
        with instrumentation(None if current else namespace) as counts:
            tracemalloc.start()
            started = time.perf_counter();heart.start(started)
            try:
                yield from action()
                # Deliver paint callbacks before stopping the operation timer.
                yield lambda: True
                seconds = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                # Fast work still has enough heartbeat samples; retain maxima.
                yield lambda: heart.ready(time.perf_counter())
                hb = heart.finish(time.perf_counter())
            finally:
                tracemalloc.stop()
        after = app._ledger_cache.metrics() if current else {}
        row = {'phase': name, 'seconds': seconds, 'python_allocation_peak_bytes': peak,
            'counts': dict(counts), 'cache_delta': {k: after.get(k, 0) - before.get(k, 0)
                for k in ('source_reads', 'source_bytes', 'workbook_opens', 'formula_cache_opens', 'weak_hash_probes')},
            'cache_after': after, 'heartbeat': hb}
        if observed is not None:row['observed'] = observed()
        measurements.append(row)
        print('P04_PHASE ' + json.dumps({'phase': name, 'state': 'completed',
            'seconds': seconds, 'heartbeat_samples': hb['samples'], 'max_gap_ms': hb['max_gap_ms']}), file=sys.stderr, flush=True)
    def refresh():
        if current:
            yield completed(app.refresh_excel_files())
            yield lambda: len(app.excel_file_tree.get_children()) == case['files'] and app._io_last_files is app.excel_read_results
            if case['role'] == 'manager':
                yield completed(app.aggregate_all_excels(silent=True))
                yield lambda: len(app.excel_file_tree.get_children()) == case['files'] and app._io_last_files is app.excel_read_results
        else:
            original.refresh(app, case['role'])
            yield lambda: True
    path = str(next((folder / 'inputs').glob('*.xlsx')))
    def open_view():
        yield completed(app.open_excel_path(path))
        yield lambda: app._page_view is not None and app._page_view.path == path
    seen = []
    def pages():
        while True:
            rows = list(app.excel_view_row_map.values())
            if len(rows) > 200:raise AssertionError('PAGE_EXCEEDS_200_ROWS')
            seen.extend(rows)
            if (app._page_number + 1) * 200 >= len(app._page_indices):break
            app.excel_next_button.invoke()
            yield lambda: True
    def page_observation():
        wanted = case['detail_rows_per_file'] + (6 if case['role'] == 'manager' else 0)
        if len(seen) != len(set(seen)) or len(seen) != wanted:
            raise AssertionError('PAGE_ROWS_MISSING_OR_DUPLICATED')
        if app._page_view.ledger.detail_count != case['detail_rows_per_file']:
            raise AssertionError('VIEW_DETAIL_COUNT_MISMATCH')
        amounts = app._page_view.ledger.totals
        if (amounts.income_cents, amounts.cost_cents, amounts.profit_cents) != (case['detail_rows_per_file'] * 1000, case['detail_rows_per_file'] * 400, case['detail_rows_per_file'] * 600):
            raise AssertionError('VIEW_TOTALS_MISMATCH')
        return {'visible_rows': len(seen), 'detail_rows': app._page_view.ledger.detail_count, 'pages': app._page_number + 1,
                'all_rows_reachable': True, 'exact_income_cents': app._page_view.ledger.totals.income_cents}
    def filter_rows():
        app.excel_filter_var.set(f"合成订单{case['detail_rows_per_file'] - 1:06d}")
        app.excel_filter_button.invoke()
        yield completed(app._io_runtime.latest['view'])
    def filter_observation():
        if list(app.excel_view_row_map.values()) != [case['detail_rows_per_file'] + 6]:
            raise AssertionError('FILTER_DID_NOT_REACH_LAST_DETAIL')
        return {'last_detail_reachable': True, 'source_row': case['detail_rows_per_file'] + 6}
    def sequence():
        # Constructors queue a delayed refresh (300ms) in both archived and
        # live entrypoints. It must finish on the empty startup directory,
        # before synthetic inputs/cache and phase instrumentation are enabled.
        yield lambda: not startup_jobs.intersection(window.tk.splitlist(window.tk.call('after', 'info')))
        if current:
            yield lambda: not app._io_starting and app._storage_valid and not app._io_callbacks and not app._io_runtime.tasks and not app._after_jobs
        else:
            yield lambda: True
        point_at_inputs(app, folder, current)
        # Startup has no test inputs. Hash checking/setup are outside phases.
        # Both live and immutable original entrypoints own this frame. Display
        # labels include padding and are not a stable page identifier.
        app.notebook.select(app.excel_page)
        yield lambda: True
        yield from phase('first_refresh', refresh, observed=lambda: observations(app, case, current))
        yield from phase('warm_refresh', refresh, observed=lambda: observations(app, case, current))
        if current:
            yield from phase('open_view', open_view)
            yield from phase('all_pages', pages, observed=page_observation)
            yield from phase('filter_last_detail', filter_rows, observed=filter_observation)
    try:
        app = cls(window)
        startup_jobs = set(window.tk.splitlist(window.tk.call('after', 'info'))) - {getattr(app, '_io_poll_job', None)}
        if current:
            original_feedback = app.set_feedback
            def tracked_feedback(text, is_error=False):
                original_feedback(text, is_error=is_error)
                if is_error:feedback_errors.append(str(text))
            app.set_feedback = tracked_feedback
        print('P04_PHASE ' + json.dumps({'phase': 'startup', 'state': 'started'}), file=sys.stderr, flush=True)
        window.protocol('WM_DELETE_WINDOW', lambda: None)
        active_context = sequence()
        deadline = time.monotonic() + 120
        def drive():
            nonlocal waiting, error, error_cause, deadline
            try:
                if time.monotonic() > deadline:raise TimeoutError('GUI_PHASE_DEADLINE')
                if waiting is None or waiting():
                    waiting = next(active_context);deadline = time.monotonic() + 120
                window.after(10, drive)
            except StopIteration:window.quit()
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}';error_cause = exc;window.quit()
        with patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror'), patch('tkinter.messagebox.showwarning'):
            heartbeat_jobs[:] = [window.after(50, pulse)]
            window.after(10, drive);window.mainloop()
        if error:raise RuntimeError(f'{active_phase}: {error}') from error_cause
        if errors:raise RuntimeError('TK_CALLBACK_ERRORS: ' + repr(errors))
        return measurements, {'callback_errors': errors, 'close': 'ok', 'user_input_disabled': True,
            'tk_version': window.tk.call('package', 'provide', 'Tk'),
            'tcl_version': window.tk.call('info', 'patchlevel'), 'tk_scaling': float(window.tk.call('tk', 'scaling')),
            'scope': 'Actual Windows Tk mainloop; 50ms after; measured refresh/view/page/filter plus idle settling; no fixtures/verification/image capture inside phases'}
    finally:
        if active_context is not None:active_context.close()
        for job in heartbeat_jobs:
            try:window.after_cancel(job)
            except tk.TclError:pass
        if app is not None:
            app.on_close()
            if current and not app._io_runtime.wait_closed(5):
                raise TimeoutError('READ_WORKERS_NOT_FINISHED_BEFORE_CLEANUP')
        try:window.destroy()
        except tk.TclError:pass  # app.on_close already destroys its root.
        window.tk.call('update')
        if errors:raise RuntimeError('TK_CALLBACK_ERRORS_ON_CLOSE: ' + repr(errors))


def worker(root, case_id, version, native=False):
    if native and platform.system() != 'Windows':
        raise ValueError('WINDOWS_GUI_ONLY')
    case, folder = get_case(root, case_id)
    current = version == 'current'
    if current:
        namespace = prepare_current(folder, case['role'])
    else:
        manifest, _ = original.gate()
        entry = next(e for e in manifest['files'] if e['role'] == case['role'])
        namespace = baseline_check.sandbox_namespace(ROOT, entry, folder)
    if native:
        measurements, lifecycle = gui_measurements(namespace, folder, case, current)
    else:
        app = headless_app(namespace, folder, current)
        measurements = [measure_headless(app, namespace, case, current, condition)
                        for condition in ('first_refresh', 'warm_refresh')]
        lifecycle = {'scope': 'Original methods with control stubs or current background scan model; no actual Tk/heartbeat'}
    if input_hashes(folder / 'inputs') != case['input_sha256']:
        raise AssertionError('READ_ONLY_INPUTS_MODIFIED')
    return {'version': version, 'case_id': case_id, 'status': 'measured', 'measurements': measurements,
        'lifecycle': lifecycle, 'inputs_unchanged': True, 'scope': lifecycle['scope'], 'tracemalloc_enabled': True,
        'cold_scope': 'Fresh process/cache; OS/SMB server cache uncontrolled and input hashing reads bytes before measurement'}


def launch_worker(root, case, version, native, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', version, '--worker-root', str(root),
               '--case', case['id']]
    if native:command.append('--gui-heartbeat')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=timeout,
            cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        if result.returncode:
            return {'status': 'worker_failed', 'case_id': case['id'], 'version': version,
                    'returncode': result.returncode, 'stderr': result.stderr}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ''
        if isinstance(stderr, bytes):stderr = stderr.decode('utf-8', errors='replace')
        phases = []
        for line in stderr.splitlines():
            if line.startswith('P04_PHASE '):
                try:phases.append(json.loads(line[len('P04_PHASE '):]))
                except ValueError:pass
        return {'status': 'timeout', 'case_id': case['id'], 'version': version, 'timeout_seconds': timeout,
            'stderr': stderr, 'last_phase': phases[-1].get('phase') if phases else None,
            'scope': 'Read-only diagnostic subprocess terminated; metrics unavailable, not a successful sample. No write transaction runs in this worker.'}


def summarize(runs, cases, rounds, native):
    rows = []
    accepted = limits()
    for case in cases:
        for version in ('original', 'current'):
            selected = [r for r in runs if r['case_id'] == case['id'] and r['version'] == version]
            if not selected:continue
            phases = sorted({m['phase'] for r in selected for m in r.get('measurements', [])})
            for phase in phases:
                measurements = [m for r in selected if r['status'] == 'measured' for m in r['measurements'] if m['phase'] == phase]
                heartbeats = [m['heartbeat'] for m in measurements if isinstance(m['heartbeat'], dict)]
                counts = [m['counts'].get('workbook_opens', 0) for m in measurements]
                healthy = native and len(heartbeats) == rounds and all(healthy_heartbeat(h, accepted['heartbeat_p95_ms'], accepted['heartbeat_max_ms']) for h in heartbeats)
                exact = all(m.get('observed', {}).get('correct', True) for m in measurements)
                decode = all(n == (case['files'] if phase == 'first_refresh' else 0) for n in counts) if phase in {'first_refresh', 'warm_refresh'} and version == 'current' else True
                complete = len(measurements) == rounds and rounds >= 5 and all(r['status'] == 'measured' for r in selected)
                row = {'case_id': case['id'], 'version': version, 'phase': phase,
                    'seconds': distribution([m['seconds'] for m in measurements]),
                    'python_allocation_peak_bytes': distribution([m['python_allocation_peak_bytes'] for m in measurements]),
                    'workbook_opens_each_round': counts, 'worksheet_xml_source_opens_each_round': [m['counts'].get('worksheet_xml_source_opens', 0) for m in measurements],
                    'correct': exact, 'expected_cold_warm_decodes': decode, 'complete_five_rounds': complete,
                    'heartbeat_healthy_each_round': healthy if native else 'not_measured',
                    'heartbeat_max_ms_each_round': [h['max_gap_ms'] for h in heartbeats],
                    'heartbeat_p95_ms_each_round': [h['p95_gap_ms'] for h in heartbeats]}
                rows.append(row)
    current_runs = [r for r in runs if r['version'] == 'current']
    current_rows = [r for r in rows if r['version'] == 'current']
    wanted = {'first_refresh', 'warm_refresh', 'open_view', 'all_pages', 'filter_last_detail'} if native else {'first_refresh', 'warm_refresh'}
    all_current = bool(current_rows) and len(current_runs) == len(cases) * rounds and all(
        r['status'] == 'measured' and r['inputs_unchanged'] and {m['phase'] for m in r['measurements']} == wanted for r in current_runs)
    current_correct = all_current and all(r['correct'] and r['expected_cold_warm_decodes'] for r in current_rows)
    full_requested = len(cases) == 9 and rounds >= 5
    full = full_requested and all_current and all(r['complete_five_rounds'] for r in current_rows)
    healthy = native and full and current_correct and all(r['complete_five_rounds'] and r['heartbeat_healthy_each_round'] for r in current_rows)
    return {'phases': rows, 'current_correctness_and_read_counts_passed': current_correct,
        'full_scale_five_rounds_requested': full_requested, 'full_scale_five_rounds': full,
        'Windows_healthy_performance_passed': healthy,
        'memory_scope': 'tracemalloc Python allocations during each phase, not process RSS; retained cache estimates also in raw samples',
        'comparison_scope': 'Matched workbook bytes, device/process settings, counts and tracemalloc. Original known cost defect remains; no financial equivalence or inferred percentage speedup.'}


def shared_parent(text):
    if platform.system() != 'Windows' or not text.startswith('\\\\'):
        raise ValueError('SHARED_ROOT_REQUIRES_EXPLICIT_WINDOWS_UNC')
    path = Path(text)
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)() or not path.is_dir():
        raise ValueError('SHARED_ROOT_MUST_BE_EXISTING_DIRECTORY_WITHOUT_LINK')
    return path


def legacy_complete(runs, cases, rounds, legacy_sizes):
    wanted = [c for c in cases if c['legacy_p01_workload'] and c['size'] in legacy_sizes]
    return bool(wanted) and all(
        len(selected := [r for r in runs if r['version'] == 'original' and r['case_id'] == case['id']]) == rounds
        and all(r['status'] == 'measured' and r.get('inputs_unchanged') and
                {m['phase'] for m in r['measurements']} == {'first_refresh', 'warm_refresh'} for r in selected)
        for case in wanted)


def compact_storage(storage):
    summary = storage['summary']
    native = [(m['heartbeat']['max_gap_ms'], r['case_id'], m['phase'], r['round']) for r in storage['runs']
              for m in r.get('measurements', []) if r['version'] == 'current' and isinstance(m['heartbeat'], dict)]
    worst = max(native, default=None)
    return {'storage': storage['storage'], 'inputs_unchanged': storage['inputs_unchanged'],
        'sandbox_cleaned': storage['sandbox_cleaned'],
        'correctness_and_read_counts_passed': summary['current_correctness_and_read_counts_passed'],
        'full_scale_five_rounds': summary['full_scale_five_rounds'],
        'Windows_healthy_performance_passed': summary['Windows_healthy_performance_passed'],
        'worst_current_heartbeat': {'max_gap_ms': worst[0], 'case': worst[1], 'phase': worst[2], 'round': worst[3]} if worst else None,
        'worker_failures': [{k: r.get(k) for k in ('case_id', 'version', 'round', 'status', 'timeout_seconds')} for r in storage['runs'] if r['status'] != 'measured']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gui-heartbeat', action='store_true')
    mode.add_argument('--auxiliary', action='store_true')
    mode.add_argument('--checks-only', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sizes', nargs='+', choices=tuple(SIZES), default=list(SIZES))
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--compare-legacy', action='store_true', help='Replay P01 original workloads on identical inputs; default small baseline')
    parser.add_argument('--legacy-sizes', nargs='+', choices=tuple(SIZES), default=['small'])
    parser.add_argument('--worker-timeout', type=float, default=120)
    parser.add_argument('--shared-root', help='Explicit UNC parent; creates and cleans one exclusive synthetic child, never scans parent workbooks')
    parser.add_argument('--worker', choices=('original', 'current'), help=argparse.SUPPRESS)
    parser.add_argument('--worker-root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--case', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        print(json.dumps(worker(args.worker_root, args.case, args.worker, args.gui_heartbeat), ensure_ascii=False, allow_nan=False))
        return 0
    if not args.output or not any((args.gui_heartbeat, args.auxiliary, args.checks_only)):
        parser.error('Select --gui-heartbeat, --auxiliary or --checks-only and a NEW --output reports/<directory>')
    if not 1 <= args.rounds <= 10 or (args.gui_heartbeat and args.rounds < 5) or not 5 <= args.worker_timeout <= 600:
        parser.error('Windows acceptance requires at least 5 rounds; allowed rounds 1..10, worker timeout 5..600 seconds')
    if args.shared_root and not args.gui_heartbeat:
        parser.error('--shared-root requires actual Windows --gui-heartbeat')
    output = original.new_output(args.output)
    checks = run_checks()
    fingerprints = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for p in sorted([*ROOT.glob('quote_app/*.py'), *ROOT.glob('quote_files/*.py'), *ROOT.glob('quote_core/*.py'), *ROOT.glob('报价*.py'),
            ROOT / 'tools/p04_metrics.py', ROOT / 'tools/p01_fixtures.py', ROOT / 'tools/p01_validation.py', ROOT / 'tools/p02_gui_check.py',
            ROOT / 'tools/baseline_check.py', ROOT / 'tests/test_performance_measurement.py', Path(__file__)])}
    report = {'task': 'P04-04', 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'environment': {'os': platform.system(), 'release': platform.release(), 'python': platform.python_version(),
            'python_executable': sys.executable, 'openpyxl': __import__('openpyxl').__version__, 'pillow': __import__('PIL').__version__,
            'machine': platform.machine(), 'processor': platform.processor(), 'device': platform.node()}, 'limits': limits(), 'checks': checks,
        'implementation_sha256_LF': fingerprints, 'production_files_read_or_modified': False,
        'production_paths_accessed': bool(args.shared_root), 'explicit_shared_root_requested': bool(args.shared_root),
        'status': checks['status'], 'storages': [],
        'previous_563ms_observation': 'P04-03 report retained unchanged; that single whole-diagnostic maximum has no phase attribution. New stage samples measure actual workflows; they cannot retrospectively assign its cause.',
        'prior_lifecycle_and_financial_evidence': ['docs/verification/P04-03-windows-evidence-02.json', 'docs/verification/P04-03-acceptance.json'],
        'acceptance': 'P04-04 and entire P04 user acceptance pending; only actual Windows/UNC results can establish performance. No physical offline or two-machine contention tests are scheduled.'}
    if checks['status'] != 'passed' or args.checks_only:
        pass
    elif args.gui_heartbeat and platform.system() != 'Windows':
        report.update(status='blocked', reason='Actual Windows Tk required; no GUI constructed and no shared path accessed', production_paths_accessed=False)
    else:
        try:
            parents = [('local', None)]
            if args.shared_root:parents.append(('UNC_synthetic', shared_parent(args.shared_root)))
            for storage, parent in parents:
                with tempfile.TemporaryDirectory(prefix='777-p04-performance-', dir=parent) as temp:
                    root = Path(temp);cases = make_inputs(root, list(dict.fromkeys(args.sizes)))
                    runs = []
                    for case in cases:
                        versions = ['current']
                        if args.compare_legacy and case['legacy_p01_workload'] and case['size'] in args.legacy_sizes:
                            versions.insert(0, 'original')
                        for version in versions:
                            for round_ in range(args.rounds):
                                print(f"P04-04 {storage}: {case['id']} {version} {round_+1}/{args.rounds}", file=sys.stderr, flush=True)
                                result = launch_worker(root, case, version, args.gui_heartbeat, args.worker_timeout)
                                result['round'] = round_ + 1;runs.append(result)
                                fixtures.write_json(output / 'report.json', {**report, 'status': 'running', 'in_progress': {'storage': storage, 'case': case['id'], 'version': version, 'round': round_ + 1}, 'partial_runs': runs})
                                if result['status'] != 'measured':break
                    inputs_unchanged = all(input_hashes(root / c['id'] / 'inputs') == c['input_sha256'] for c in cases)
                    summary = summarize(runs, cases, args.rounds, args.gui_heartbeat)
                    entry = {'storage': storage, 'temporary_root': str(root), 'temporary_directory_only': True,
                        'dataset_manifest': json.loads((root / 'p04-run.json').read_text(encoding='utf-8')),
                        'runs': runs, 'summary': summary, 'inputs_unchanged': inputs_unchanged,
                        'native_Tk': args.gui_heartbeat, 'legacy_sizes_requested': args.legacy_sizes if args.compare_legacy else [],
                        'matched_legacy_rounds_complete': legacy_complete(runs, cases, args.rounds, args.legacy_sizes) if args.compare_legacy else False,
                        'sandbox_cleaned': False}
                    report['storages'].append(entry)
                entry['sandbox_cleaned'] = True
            good = all(s['inputs_unchanged'] and s['summary']['current_correctness_and_read_counts_passed'] for s in report['storages'])
            if not good:report['status'] = 'failed'
            elif not args.gui_heartbeat:report['status'] = 'auxiliary_measured_Windows_pending'
            elif not all(s['summary']['Windows_healthy_performance_passed'] for s in report['storages']):report['status'] = 'performance_not_passed_or_incomplete'
            elif not args.compare_legacy or not all(s['matched_legacy_rounds_complete'] for s in report['storages']):
                report['status'] = 'matched_original_comparison_incomplete'
            elif not args.shared_root:report['status'] = 'local_performance_passed_UNC_pending'
            else:report['status'] = 'Windows_local_and_UNC_synthetic_performance_passed'
        except Exception as exc:
            report.update(status='failed', error=f'{type(exc).__name__}: {exc}',
                          failure_scope='Input preparation/worker orchestration/cleanup did not complete; partial snapshots are not acceptance.')
    fixtures.write_json(output / 'report.json', report)
    print(json.dumps({'task': report['task'], 'status': report['status'], 'checks': {k: v for k, v in checks.items() if k not in {'log', 'test_ids'}},
        'report': str(output / 'report.json'), 'storages': [compact_storage(s) for s in report['storages']]}, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if report['status'] in {'passed', 'auxiliary_measured_Windows_pending', 'Windows_local_and_UNC_synthetic_performance_passed'} else 2


if __name__ == '__main__':raise SystemExit(main())
