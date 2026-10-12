"""Strict wire inputs and explicit role projections. Financial cents are strings."""
from dataclasses import asdict
import json
from quote_core import NormalLine, DiscountLine, QuoteSnapshot, DraftDetails, PriceItem, PriceSnapshot
from quote_core.numbers import RULE_VERSION, NUMERIC_PROFILE

BODY_LIMIT = 1024 * 1024


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise APIError(422, 'INVALID_FIELDS')
    return value


def text(value, maximum=4096, *, nonempty=False):
    if type(value) is not str or len(value) > maximum or nonempty and not value.strip():
        raise APIError(422, 'INVALID_TEXT')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise APIError(422, 'INVALID_TEXT') from None
    if '\x00' in value:
        raise APIError(422, 'INVALID_TEXT')
    return value


def decode(raw, *, maximum=BODY_LIMIT):
    if len(raw) > maximum:
        raise APIError(413, 'BODY_TOO_LARGE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError, UnicodeError, RecursionError):
        raise APIError(422, 'INVALID_JSON') from None


def quote(value):
    fields(value, {'price_version_id', 'lines'}, {'rule_version', 'numeric_profile'})
    if value.get('rule_version', RULE_VERSION) != RULE_VERSION or value.get('numeric_profile', NUMERIC_PROFILE) != NUMERIC_PROFILE:
        raise APIError(409, 'PROTOCOL_VERSION_CONFLICT')
    lines = value['lines']
    if type(lines) is not list or not 1 <= len(lines) <= 1000:
        raise APIError(422, 'INVALID_LINES')
    result = []
    for line in lines:
        if type(line) is not dict:
            raise APIError(422, 'INVALID_LINE')
        if line.get('line_kind') == 'normal':
            fields(line, {'line_kind', 'product_id', 'q'}, {'h', 'w', 'name'})
            result.append(NormalLine(text(line['product_id'], 256, nonempty=True), text(line['q'], 256),
                                     text(line.get('h', ''), 256), text(line.get('w', ''), 256), text(line.get('name', ''), 256)))
        elif line.get('line_kind') == 'discount':
            fields(line, {'line_kind', 'percent'}, {'name'})
            result.append(DiscountLine(text(line['percent'], 256), text(line.get('name', '折扣'), 256)))
        else:
            raise APIError(422, 'INVALID_LINE')
    return QuoteSnapshot(text(value['price_version_id'], 256, nonempty=True), tuple(result))


def details(value):
    fields(value, {'customer', 'order_ref', 'wechat'})
    return DraftDetails(**{k: text(v) for k, v in value.items()})


def prices(value):
    fields(value, {'price_version_id', 'items'})
    if type(value['items']) is not list or not 1 <= len(value['items']) <= 1000:
        raise APIError(422, 'INVALID_PRICES')
    items = []
    for item in value['items']:
        fields(item, {'product_id', 'sale', 'cost', 'k', 'single'})
        if type(item['single']) is not bool:
            raise APIError(422, 'INVALID_PRICES')
        items.append(PriceItem(*(text(item[k], 256) for k in ('product_id', 'sale', 'cost', 'k')), item['single']))
    return PriceSnapshot(text(value['price_version_id'], 256, nonempty=True), tuple(items))


def financial(value, actor):
    # Allow-list: do not recursively redact unknown future fields.
    keys = {'order_id', 'note_id', 'revision', 'request_id', 'price_version_id', 'state', 'reason', 'income_cents'}
    if actor.role == 'admin':
        keys |= {'cost_cents', 'profit_cents', 'ledger_revision'}
    return {k: v for k, v in value.items() if k in keys}


def catalog(snapshot, actor):
    items = [asdict(item) for item in snapshot.items]
    if actor.role != 'admin':
        items = [{k: item[k] for k in ('product_id', 'sale', 'k', 'single')} for item in items]
    return {'price_version_id': snapshot.price_version_id, 'items': items,
            'rule_version': RULE_VERSION, 'numeric_profile': NUMERIC_PROFILE}


def calculated(result, actor):
    lines = []
    for line in result.lines or ():
        normalized = dict(line.normalized)
        if actor.role != 'admin':
            normalized = {k: v for k, v in normalized.items() if k in {'q', 'h', 'w', 'sale', 'k', 'percent', 'single'}}
        lines.append({'sequence': line.sequence, 'raw': asdict(line.raw), 'normalized': normalized,
                      'subtotal_before_cents': str(line.subtotal_before_cents), **financial(line.amounts.cents_payload(), actor)})
    return {'status': result.status, 'price_version_id': result.price_version_id,
            'lines': lines, 'totals': financial(result.totals.cents_payload(), actor) if result.totals else None,
            'issues': [asdict(issue) for issue in result.issues], 'warnings': [asdict(issue) for issue in result.warnings]}
