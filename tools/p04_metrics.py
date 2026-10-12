"""Performance-v1 measurements, independent of Tk and financial computation."""
from collections import Counter
from contextlib import contextmanager, ExitStack
import math
from pathlib import Path
import statistics
from threading import Lock
from unittest.mock import patch
from zipfile import ZipFile
import gc
import time
from threading import get_ident, RLock

import openpyxl
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.worksheet import Worksheet


def percentile(values, fraction=.95):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def distribution(values):
    return {'samples': len(values), 'p50': statistics.median(values) if values else None,
            'p95': percentile(values), 'max': max(values) if values else None}


def healthy_heartbeat(data, p95_limit=100, max_limit=500):
    gaps = data.get('gaps_ms', [])
    if len(gaps) < 20 or data.get('samples') != len(gaps) or any(not math.isfinite(g) or g < 0 for g in gaps):
        return False
    stats = distribution(gaps)
    return data.get('status') == 'passed' and data.get('p95_gap_ms') == stats['p95'] and data.get('max_gap_ms') == stats['max'] and stats['p95'] <= p95_limit and stats['max'] <= max_limit


class Heartbeat:
    """Record every gap inside an explicit phase, including its boundaries."""
    def __init__(self, p95_limit=100, max_limit=500):
        self.p95_limit, self.max_limit = p95_limit, max_limit
        self.last, self.gaps = None, []

    def start(self, now):
        self.started = now
        self.last, self.gaps = now, []

    def ready(self, now):
        # Timer delivery can be slower than the requested 50ms (e.g. Windows
        # clock rounding). Elapsed time alone cannot establish sample count.
        return self.last is not None and now - self.started >= 1.1 and len(self.gaps) >= 20

    def pulse(self, now):
        if self.last is not None:
            gap = (now - self.last) * 1000
            if not math.isfinite(gap) or gap < 0:
                raise ValueError('INVALID_HEARTBEAT_CLOCK')
            self.gaps.append(gap)
            self.last = now

    def finish(self, now):
        self.pulse(now)
        gaps, self.last = self.gaps, None
        stats = distribution(gaps)
        enough = len(gaps) >= 20
        passed = enough and stats['p95'] <= self.p95_limit and stats['max'] <= self.max_limit
        return {'interval_ms': 50, 'samples': len(gaps), 'p95_gap_ms': stats['p95'],
                'max_gap_ms': stats['max'], 'gaps_ms': gaps,
                'over_100_ms': sum(g > self.p95_limit for g in gaps),
                'over_500_ms': sum(g > self.max_limit for g in gaps),
                'status': 'passed' if passed else 'failed' if enough else 'insufficient_samples',
                'observation_seconds': now - self.started,
                'scope': '50ms actual Tk heartbeat during operation, at least 1.1s observation and 20 timer callbacks; includes every phase boundary gap and idle settling. Preparation and post-measurement validation are separate.'}


class LatencyTrace:
    """Read-only diagnostic spans; extra overhead never establishes acceptance.

    Function spans are nested, so their durations must not be added together.
    Time overlap with a heartbeat gap is correlation, not causal attribution.
    No arguments, locals, cell values or Tk objects are read by the recorder.
    """
    def __init__(self, max_events=4096):
        self.owner = get_ident()
        self.started = None
        self.events, self.dropped, self.max_events = [], 0, max_events
        self.lock, self.collecting = RLock(), {}

    def start(self, now):
        self.started = now

    def record(self, name, begin, end, cpu=None):
        if self.started is None:return
        event = {'name': name, 'thread': 'owner' if get_ident() == self.owner else 'worker',
                 'start_seconds': max(0, begin - self.started), 'end_seconds': max(0, end - self.started),
                 'wall_seconds': end - begin, 'thread_cpu_seconds': cpu}
        with self.lock:
            if len(self.events) < self.max_events:self.events.append(event)
            else:self.dropped += 1

    def wrap(self, name, original):
        def timed(*args, **kwargs):
            begin, cpu = time.perf_counter(), time.thread_time()
            try:return original(*args, **kwargs)
            finally:self.record(name, begin, time.perf_counter(), time.thread_time() - cpu)
        return timed

    def collection(self, phase, info):
        if self.started is None:return
        key = (get_ident(), info['generation'])
        if phase == 'start':self.collecting[key] = time.perf_counter()
        elif phase == 'stop':
            begin = self.collecting.pop(key, None)
            if begin is not None:self.record('gc.gen' + str(info['generation']), begin, time.perf_counter())

    def __enter__(self):
        from quote_files import cache, documents, reading, workbooks, orders, views, scheduling
        from quote_app import background, pagination
        targets = [(cache, 'parse_document', 'parse_document'),
            (documents, 'parse_document', 'parse_document'), (documents.Book, '__init__', 'detach_cells'),
            (reading, 'open_book', 'decode_workbook'), (workbooks, 'open_book', 'decode_workbook'),
            (reading, 'analyze', 'analyze_ledger'), (workbooks, 'view_identity', 'build_identities'),
            (orders, 'order_views', 'build_orders'), (views, 'read_view', 'build_view'),
            (cache.LedgerCache, 'get', 'cache_get'), (pagination, 'filter_view', 'filter_view'),
            (background.BackgroundApplicationMixin, '_apply_io_state', 'deliver_state'),
            (background.BackgroundApplicationMixin, '_render_io_files', 'render_file_list'),
            (pagination.PaginationMixin, '_set_paged_view', 'deliver_view'),
            (pagination.PaginationMixin, '_render_page', 'render_page'),
            (scheduling.ReadTurn, 'pause', 'cooperative_pause')]
        self.stack = ExitStack()
        try:
            for target, attr, name in targets:
                self.stack.enter_context(patch.object(target, attr, self.wrap(name, getattr(target, attr))))
            gc.callbacks.append(self.collection)
            self.stack.callback(lambda: gc.callbacks.remove(self.collection))
            return self
        except Exception:
            self.stack.close();raise

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def snapshot(self, heartbeat):
        events = sorted(self.events, key=lambda e: e['start_seconds'])
        gaps, cursor = [], 0
        for interval in heartbeat.get('gaps_ms', []):
            end = cursor + interval / 1000
            if interval > 100:
                overlaps = [e for e in events if e['start_seconds'] < end and e['end_seconds'] > cursor]
                gc_overlap = sum(max(0, min(end, e['end_seconds']) - max(cursor, e['start_seconds']))
                                 for e in overlaps if e['name'].startswith('gc.'))
                gaps.append({'start_seconds': cursor, 'end_seconds': end, 'gap_ms': interval,
                    'owner_spans': sorted({e['name'] for e in overlaps if e['thread'] == 'owner'}),
                    'worker_spans': sorted({e['name'] for e in overlaps if e['thread'] == 'worker'}),
                    'gc_overlap_ms': gc_overlap * 1000})
            cursor = end
        return {'events': events, 'events_dropped': self.dropped, 'unfinished_gc': len(self.collecting),
                'over_100_ms_gaps': gaps, 'extra_instrumentation': True,
                'scope': 'Aligned nested function/GC spans and per-thread CPU; overlap is correlation, not proof of cause. Never add nested durations or accept performance from diagnostic mode.'}


@contextmanager
def instrumentation(namespace=None):
    """Count matching library boundaries for original and current implementations."""
    counts, lock = Counter(), Lock()
    def increment(key):
        with lock:
            counts[key] += 1
    opened = openpyxl.load_workbook
    xml_open = ZipFile.open
    source = ReadOnlyWorksheet._get_source
    regular_rows, readonly_rows = Worksheet.iter_rows, ReadOnlyWorksheet.iter_rows
    def load(*args, **kwargs):
        increment('workbook_opens')
        return opened(*args, **kwargs)
    def xml(package, name, *args, **kwargs):
        part = getattr(name, 'filename', name)
        if isinstance(part, str) and part.startswith('xl/worksheets/') and part.endswith('.xml'):
            increment('worksheet_xml_source_opens')
        return xml_open(package, name, *args, **kwargs)
    def read_source(sheet):
        increment('readonly_get_source_calls')
        return source(sheet)
    def rows(original):
        def counted(sheet, *args, **kwargs):
            increment('iter_rows_calls')
            for row in original(sheet, *args, **kwargs):
                increment('yielded_rows')
                yield row
        return counted
    with ExitStack() as stack:
        stack.enter_context(patch.object(openpyxl, 'load_workbook', load))
        stack.enter_context(patch.object(ZipFile, 'open', xml))
        stack.enter_context(patch.object(ReadOnlyWorksheet, '_get_source', read_source))
        stack.enter_context(patch.object(Worksheet, 'iter_rows', rows(regular_rows)))
        stack.enter_context(patch.object(ReadOnlyWorksheet, 'iter_rows', rows(readonly_rows)))
        if namespace is not None:
            globals_ = namespace['PriceCalculator'].refresh_excel_files.__globals__
            stack.enter_context(patch.dict(globals_, {'load_workbook': load}))
        yield counts


def input_hashes(folder):
    import hashlib
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).glob('*.xlsx'))}
