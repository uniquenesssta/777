"""Recognize evidence, keep source rows, and require exact core reconciliation.

No formula evaluation, current-price lookup, source write, or inferred owner.
Legacy files without stable IDs use only explicit totals or distinct single-row
prefixes. Ambiguities and changed business results remain quarantined.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import io
import os
from pathlib import Path
import stat
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from quote_core import (DiscountLine, DraftDetails, NormalLine, PriceItem,
                        PriceSnapshot, QuoteSnapshot, calculate_quote, parse_price_config)
from quote_core.numbers import NUMERIC_PROFILE, RULE_VERSION, exact_context, settle
from quote_files.documents import Book
from quote_files.reading import analyze
from quote_files.schema import inspect_schema
from quote_files.workbooks import open_book
from quote_ledger.store import encoded, text

ADAPTER_VERSION = 'legacy-import-v1'
SOURCE_LIMIT = 20 * 1024 * 1024
EXPANDED_LIMIT = 64 * 1024 * 1024
ROW_LIMIT, CELL_LIMIT = 50000, 1000000
LEGACY_TIMEZONE = timezone(timedelta(hours=8))


class ReviewRequired(ValueError):
    def __init__(self, code, difference=None):
        super().__init__(code)
        self.difference = difference


def fail(code):
    raise ReviewRequired(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_source(path):
    """Explicit file only, bounded rb read. UNC is allowed for source evidence."""
    path = Path(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            fail('SOURCE_LINK_OR_REPARSE')
    if not path.is_file():
        fail('SOURCE_NOT_REGULAR_FILE')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > SOURCE_LIMIT:
            fail('SOURCE_SIZE_LIMIT')
        raw = stream.read(SOURCE_LIMIT + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > SOURCE_LIMIT or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        fail('SOURCE_CHANGED_DURING_READ')
    return raw


@dataclass(frozen=True)
class Plan:
    source_sha256: str
    kind: str
    source_schema: str
    orders: tuple
    catalog: dict | None
    quarantined: tuple
    file_evidence: dict
    options: dict

    def payload(self):
        return {'adapter_version': ADAPTER_VERSION, **asdict(self)}

    @property
    def review_sha256(self):
        return sha(encoded(self.payload()).encode('utf-8'))

    def report(self):
        totals = [sum(o['totals'][k] for o in self.orders) for k in ('income_cents', 'cost_cents', 'profit_cents')]
        active = [sum(o['totals'][k] for o in self.orders if o['state'] == 'active') for k in ('income_cents', 'cost_cents', 'profit_cents')]
        return {'task': 'P05-03', 'adapter_version': ADAPTER_VERSION,
                'status': 'review_required' if self.quarantined else 'ready',
                'source_sha256': self.source_sha256, 'source_schema': self.source_schema, 'source_kind': self.kind,
                'review_sha256': self.review_sha256, 'eligible_orders': len(self.orders),
                'eligible_lines': sum(len(o['snapshot']['lines']) for o in self.orders),
                'eligible_notes': sum(len(o['notes']) for o in self.orders),
                'catalog_items': len(self.catalog['items']) if self.catalog else 0,
                'eligible_all_order_totals_cents': dict(zip(('income', 'cost', 'profit'), map(str, totals))),
                'eligible_active_order_totals_cents': dict(zip(('income', 'cost', 'profit'), map(str, active))),
                'source_read_active_totals_cents': self.file_evidence.get('source_read_active_totals_cents'),
                'quarantined': list(self.quarantined), 'source_modified': False,
                'prices_published_or_directories_changed': False,
                'timezone_assumption': 'Naive legacy times interpreted as UTC+08:00; original text retained.'}


def scalar(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or type(value) in (str, int, float, bool):
        return value
    return str(value)


def raw_text(value, *, empty=False):
    if value is None and empty:
        return ''
    if type(value) not in (str, int, float, Decimal):
        fail('INVALID_INPUT_SCALAR')
    result = str(value)
    if len(result) > 256:
        fail('INPUT_TEXT_LIMIT')
    return result


def identity_text(value):
    if value is None:
        return ''
    if type(value) is not str:
        fail('IDENTITY_NON_TEXT')
    return text(value)


def legacy_time(value):
    original = value.isoformat() if isinstance(value, datetime) else identity_text(value)
    if len(original) < 16:
        fail('TIMESTAMP_WITHOUT_TIME')
    try:
        parsed = datetime.fromisoformat(original)
    except ValueError:
        fail('TIMESTAMP_UNSUPPORTED')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LEGACY_TIMEZONE)
    return original, parsed.astimezone(timezone.utc).isoformat()


def preflight_xlsx(raw):
    """Reject ZIP/XML expansion and formulas before openpyxl creates cells."""
    with ZipFile(io.BytesIO(raw)) as package:
        entries = package.infolist()
        if len(entries) > 2048 or len({e.filename for e in entries}) != len(entries):
            fail('ZIP_STRUCTURE_LIMIT')
        if sum(e.file_size for e in entries) > EXPANDED_LIMIT:
            fail('ZIP_EXPANSION_LIMIT')
        cells = 0
        for entry in entries:
            name = entry.filename.lower()
            if entry.flag_bits & 1:
                fail('ENCRYPTED_ZIP_UNSUPPORTED')
            if any(token in name for token in ('externallinks', 'vbaproject', 'customxml', 'embeddings', 'drawings', 'vml')):
                fail('WORKBOOK_EXTENSION_REVIEW')
            if not name.endswith('.xml'):
                continue
            data = package.read(entry)
            if b'\x00' in data:
                fail('XML_ENCODING_UNSUPPORTED')
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                fail('XML_ENTITY_UNSUPPORTED')
            if name.startswith('xl/worksheets/'):
                for _, node in ET.iterparse(io.BytesIO(data), events=('end',)):
                    tag = node.tag.rsplit('}', 1)[-1]
                    if tag == 'f':
                        fail('FORMULA_PRESENT_NO_EVALUATION_OR_CACHE_TRUST')
                    if tag == 'row' and int(node.get('r', '0')) > ROW_LIMIT:
                        fail('WORKSHEET_ROW_LIMIT')
                    if tag == 'c':
                        cells += 1
                        if cells > CELL_LIMIT:
                            fail('WORKSHEET_CELL_LIMIT')
                    node.clear()


def historical_prices(items):
    payload = {'items': items}
    parsed = parse_price_config(encoded(payload), price_version_id='import-validation')
    if parsed.status != 'ok':
        fail('HISTORICAL_PRICE_INVALID')
    canonical = {'items': [{'name': p.product_id, 'sale': p.sale, 'cost': p.cost, 'k': p.k, 'single': p.single}
                           for p in parsed.config.prices.items]}
    version = 'import-price-' + sha(encoded(canonical).encode('utf-8'))
    return PriceSnapshot(version, parsed.config.prices.items)


def model(order):
    prices = historical_prices(order['prices']['items'])
    lines = []
    for data in order['snapshot']['lines']:
        item = dict(data)
        kind = item.pop('line_kind')
        lines.append(NormalLine(**item) if kind == 'normal' else DiscountLine(**item))
    return prices, QuoteSnapshot(prices.price_version_id, tuple(lines))


def build_order(book, result, indices, key, views, note_rows):
    ws, h = book['利润明细'], result.schema.columns
    value = lambda row, field: ws.cell(row, h[field]).value if field in h else None
    records = [{'sheet': '利润明细', 'row': row,
                'values': {field: scalar(value(row, field)) for field in h}} for row in indices]
    rows = {r.index: r for r in result.rows}
    detail = [i for i in indices if rows[i].kind != 'order_total']
    footer = [i for i in indices if rows[i].kind == 'order_total']
    if not detail:
        fail('ORDER_WITHOUT_DETAILS')
    prefix = lambda row: tuple(scalar(value(row, f)) for f in ('记录时间', '淘宝ID', '订单号', '微信号'))
    if len({prefix(i) for i in indices}) != 1:
        fail('ORDER_IDENTITY_FIELDS_DIFFER')
    first = detail[0]
    source_time, created = legacy_time(value(first, '记录时间'))
    details = DraftDetails(*(identity_text(value(first, f)) for f in ('淘宝ID', '订单号', '微信号')))
    lines, items, fallbacks = [], {}, []
    for row in detail:
        def original(raw_field, normalized):
            raw_value = value(row, raw_field)
            if raw_value is None or raw_value == '':
                fallbacks.append({'row': row, 'field': raw_field, 'source': normalized})
                return raw_text(value(row, normalized), empty=normalized == 'K系数')
            return raw_text(raw_value)
        name = identity_text(value(row, '项目名称'))
        discount = rows[row].kind == 'discount' or (not result.schema.tagged and value(row, '是否单件') == '折扣' and value(row, '基础类型') == '折扣')
        if discount:
            if value(row, '基础类型') not in (None, '', '折扣') or value(row, '是否单件') not in (None, '', '折扣'):
                fail('DISCOUNT_SHAPE_UNSUPPORTED')
            lines.append(DiscountLine(raw_text(value(row, '折扣')), name))
            fallbacks.append({'row': row, 'field': '折扣原始表达式', 'source': '折扣导出文本；未保存的表达式不推测'})
            continue
        unit = value(row, '是否单件')
        if unit not in ('是', '否'):
            fail('UNIT_KIND_UNSUPPORTED')
        product = identity_text(value(row, '基础类型'))
        price = {'name': product, 'sale': original('销售单价原文', '销售单价'),
                 'cost': original('成本单价原文', '成本单价'),
                 'k': original('K系数原文', 'K系数'), 'single': unit == '是'}
        if product in items and items[product] != price:
            fail('INCONSISTENT_PRICE_WITHIN_ORDER')
        items[product] = price
        lines.append(NormalLine(product, original('数量原文', '数量'),
                                '' if unit == '是' else original('高度原文', '高度(m)'),
                                '' if unit == '是' else original('宽度原文', '宽度(m)'), name))
    source_oid = key[1] if key[0] == 'order' else None
    source_view = views.get(source_oid) if source_oid else None
    source_price_version = None
    if source_view and source_view.prices:
        history = source_view.prices
        if any(p['规则版本'] != RULE_VERSION or p['数值版本'] != NUMERIC_PROFILE for p in history):
            fail('HISTORICAL_RULE_VERSION_UNSUPPORTED')
        if len({p['价格版本'] for p in history}) != 1:
            fail('HISTORICAL_PRICE_VERSION_CONFLICT')
        source_price_version = history[0]['价格版本']
        full = {}
        for p in history:
            product = identity_text(p['项目名称'])
            if product in full or p['是否单件'] not in ('是', '否'):
                fail('HISTORICAL_PRICE_TABLE_INVALID')
            full[product] = {'name': product, 'sale': raw_text(p['销售单价原文']),
                             'cost': raw_text(p['成本单价原文']), 'k': raw_text(p['K系数原文'], empty=True),
                             'single': p['是否单件'] == '是'}
        for product, price in items.items():
            if product not in full:
                fail('LINE_PRICE_HISTORY_MISMATCH')
            product_rows = [i for i in detail if value(i, '基础类型') == product]
            for field, label in (('sale', '销售单价原文'), ('cost', '成本单价原文'), ('k', 'K系数原文')):
                if all(value(i, label) in (None, '') for i in product_rows):
                    price[field] = full[product][field]
        if any(full.get(product) != price for product, price in items.items()):
            fail('LINE_PRICE_HISTORY_MISMATCH')
        items = full
    prices = historical_prices(list(items.values()))
    snapshot = QuoteSnapshot(prices.price_version_id, tuple(lines))
    calculated = calculate_quote(snapshot, prices)
    if calculated.status != 'ok':
        fail('CORE_INPUT_REJECTED')
    for row, line in zip(detail, calculated.lines):
        saved = tuple(settle(v) for v in rows[row].values)
        actual = (line.amounts.income_cents, line.amounts.cost_cents, line.amounts.profit_cents)
        if saved != actual:
            raise ReviewRequired('HISTORICAL_AMOUNT_DIFFERS_FROM_CORE',
                                 {'row': row, 'source_cents': list(map(str, saved)), 'core_cents': list(map(str, actual))})
        fields = dict(line.normalized)
        if line.raw.line_kind == 'discount':
            coefficient = value(row, '折扣系数')
            if coefficient not in (None, '') and Decimal(raw_text(coefficient)) != exact_context().multiply(Decimal(fields['percent']), Decimal('.01')):
                fail('DISCOUNT_COEFFICIENT_DIFFERS')
            before = value(row, '折前销售额')
            if before not in (None, '') and settle(Decimal(raw_text(before))) != line.subtotal_before_cents:
                fail('DISCOUNT_SUBTOTAL_DIFFERS')
        if line.raw.line_kind == 'normal':
            for label, field in (('数量', 'q'), ('销售单价', 'sale'), ('成本单价', 'cost'), ('K系数', 'k')):
                recorded = value(row, label)
                if recorded not in (None, '') and Decimal(raw_text(recorded)) != Decimal(fields[field]):
                    fail('RAW_AND_NORMALIZED_INPUT_DIFFER')
            if not line.price.single:
                for label, field in (('高度(m)', 'h'), ('宽度(m)', 'w')):
                    if Decimal(raw_text(value(row, label))) != Decimal(fields[field]):
                        fail('RAW_AND_NORMALIZED_INPUT_DIFFER')
    totals = calculated.totals
    if footer and any(tuple(settle(v) for v in rows[i].values) != (totals.income_cents, totals.cost_cents, totals.profit_cents) for i in footer):
        fail('HISTORICAL_TOTAL_DIFFERS_FROM_CORE')
    notes = []
    if source_view and source_view.notes:
        notes = [{'source_request_id': rid, 'source_sheet': '订单备注', 'source_row': note_rows[rid],
                  'body': text(body, 4096, True)} for rid, body in source_view.notes]
        old = value(footer[0], '备注') if footer else None
        if old is not None and old != '\n'.join(n['body'] for n in notes):
            fail('NOTE_HISTORY_AND_TOTAL_DIFFER')
    else:
        for record in records:
            body = record['values'].get('备注')
            if body not in (None, ''):
                notes.append({'source_sheet': '利润明细', 'source_row': record['row'], 'body': text(identity_text(body), 4096, True)})
    events = {event[0]: event for event in source_view.events} if source_view else {}
    for note in notes:
        event = events.get(note.get('source_request_id'))
        note['created_at'] = legacy_time(event[2])[1] if event else created
        note['time_source'] = 'source_receipt' if event else 'order_time_assumption'
    states = {rows[i].state for i in indices}
    if len(states) != 1:
        fail('ORDER_STATE_DIFFERS')
    return {'source_key': list(key), 'source_order_id': source_oid,
            'source_price_version': source_price_version,
            'source_revision': source_view.revision if source_view else None,
            'source_time': source_time, 'created_at': created, 'details': asdict(details),
            'state': states.pop(), 'snapshot': asdict(snapshot),
            'prices': {'items': [{'name': p.product_id, 'sale': p.sale, 'cost': p.cost, 'k': p.k, 'single': p.single} for p in prices.items]},
            'totals': {'income_cents': totals.income_cents, 'cost_cents': totals.cost_cents, 'profit_cents': totals.profit_cents},
            'notes': notes, 'source_events': list(source_view.events) if source_view else [],
            'source_records': records, 'normalized_fallbacks': fallbacks}


def result_views(book, schema):
    from quote_files.orders import order_views
    return order_views(book, schema) if schema.identified else {}


def xlsx_plan(raw, options, native=None):
    if native is None:
        preflight_xlsx(raw)
        source = open_book(raw, for_write=False)
        try:
            if any(s.max_row > ROW_LIMIT or s.max_column > 64 or s.max_row * s.max_column > CELL_LIMIT for s in source.worksheets):
                fail('WORKSHEET_DIMENSION_LIMIT')
            book = Book(source)
        finally:
            source.close()
    else:
        from quote_files.native_excel import FormatReview
        try: book = native.excel_book(raw)
        except FormatReview as exc: raise ReviewRequired(str(exc), exc.location) from None
    schema = inspect_schema(book)
    if any(reason for reason in schema.readonly_reasons if not reason.startswith('历史记录没有行类型')):
        fail('WORKBOOK_LAYOUT_OR_APPENDIX_REVIEW')
    result = analyze(book)
    if result.status != 'ok':
        fail(result.issues[-1].code if result.issues else 'LEDGER_READ_FAILED')
    views = result_views(book, result.schema)
    note_rows = {book['订单备注'].cell(i, 1).value: i for i in range(2, book['订单备注'].max_row + 1)} if '订单备注' in book.sheetnames else {}
    groups, pending, quarantine = {}, [], []
    def flush():
        for row in pending:
            key = result.group_keys.get(row.index)
            if key and key[0] == 'legacy':
                groups.setdefault(key, []).append(row.index)
            else:
                quarantine.append({'code': 'AMBIGUOUS_ORDER_BOUNDARY', 'sheet': '利润明细', 'rows': [row.index]})
        pending.clear()
    for row in result.rows:
        oid = book['利润明细'].cell(row.index, schema.columns['订单ID']).value if schema.identified else None
        if oid:
            flush()
            groups.setdefault(('order', oid), []).append(row.index)
        elif row.kind == 'order_total':
            keys = {result.group_keys.get(p.index) for p in pending}
            if len(keys) == 1 and pending and next(iter(keys)) and next(iter(keys))[0] == 'legacy_block':
                groups[next(iter(keys))] = [p.index for p in pending] + [row.index]
                pending.clear()
            else:
                flush()
                quarantine.append({'code': 'UNBOUND_LEGACY_TOTAL', 'sheet': '利润明细', 'rows': [row.index]})
        else:
            pending.append(row)
    flush()
    orders = []
    for key, indices in groups.items():
        try:
            orders.append(build_order(book, result, indices, key, views, note_rows))
        except Exception as exc:
            code = str(exc) if isinstance(exc, ReviewRequired) else 'ORDER_INPUT_OR_METADATA_INVALID'
            quarantine.append({'code': code, 'sheet': '利润明细', 'rows': indices,
                               'difference': getattr(exc, 'difference', None)})
    evidence = {'source_read_active_totals_cents': result.totals.cents_payload()}
    for sheet in book.worksheets:
        if sheet.title != '利润明细':
            evidence[sheet.title] = [[scalar(c.value) for c in row] for row in sheet.iter_rows()]
    return Plan(sha(raw), 'xlsx', schema.name, tuple(orders), None, tuple(quarantine), evidence, options)


def preview_bytes(raw, kind, *, legacy_single_names=None, native=None):
    options = {'legacy_single_names': sorted(legacy_single_names) if legacy_single_names is not None else None}
    if type(raw) is not bytes or len(raw) > SOURCE_LIMIT:
        raise ReviewRequired('SOURCE_TYPE_OR_SIZE_LIMIT')
    if kind not in ('xlsx', 'json'):
        raise ReviewRequired('SOURCE_KIND_UNSUPPORTED')
    try:
        if kind == 'xlsx':
            return xlsx_plan(raw, options, native)
        parsed = parse_price_config(raw, price_version_id='import-config-' + sha(raw), legacy_single_names=legacy_single_names)
        if parsed.status != 'ok':
            fail(parsed.issues[0].reason)
        prices = parsed.config.prices
        catalog = {'items': [{'name': p.product_id, 'sale': p.sale, 'cost': p.cost, 'k': p.k, 'single': p.single} for p in prices.items]}
        return Plan(sha(raw), kind, parsed.config.source_schema, (), catalog, (),
                    {'original_json': parsed.config.original_json, 'directories_preserved_as_evidence_only': True}, options)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ReviewRequired) else 'SOURCE_CORRUPT_OR_UNSUPPORTED'
        issue={'code': code, 'scope': 'entire_source'}
        if getattr(exc, 'difference', None): issue['difference']=exc.difference
        return Plan(sha(raw), kind, 'unsupported', (), None, (issue,), {}, options)
