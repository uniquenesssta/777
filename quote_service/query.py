"""query-v1: bounded pages, signed snapshot cursors and audit-delta totals."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
from collections import OrderedDict

from quote_ledger.store import verify, encoded
from .protocol import APIError, financial, text

VERSION = '777-query-v1'
ORDER_COLUMNS = 'order_id,owner_id,state,details_json,income_cents,cost_cents,profit_cents,revision,created_at'


def search_text(details, order_id):
    return ('\n'.join(json.loads(details).values())+'\n'+order_id).casefold()


class Queries:
    def __init__(self):
        self.secret = secrets.token_bytes(32); self._lock = threading.RLock()
        self.revision = None; self.rows = {}; self.summaries = OrderedDict()
        self.full_scans = self.delta_rows = 0

    def _row(self, row):
        return (row['owner_id'], row['state'], search_text(row['details_json'], row['order_id']),
                row['income_cents'], row['cost_cents'], row['profit_cents'])

    @staticmethod
    def match(row, key):
        owner, state, q = key
        return (owner is None or row[0] == owner) and (state is None or row[1] == state) and (not q or q in row[2])

    def _change(self, row, direction):
        for key, values in self.summaries.items():
            if self.match(row, key):
                values[0] += direction
                if row[1] == 'active':
                    for index in range(3): values[index+1] += direction*row[index+3]

    def synchronize(self, c, revision):
        if self.revision is None or revision < self.revision:
            self.rows = {row['order_id']: self._row(row) for row in c.execute('SELECT '+ORDER_COLUMNS+' FROM orders')}
            self.summaries.clear(); self.full_scans += 1
        elif revision != self.revision:
            ids = [row[0] for row in c.execute('SELECT DISTINCT a.order_id FROM audit_events a JOIN requests r ON a.request_id=r.request_id WHERE r.ledger_revision>? AND r.ledger_revision<=? AND a.order_id IS NOT NULL', (self.revision, revision))]
            for identifier in ids:
                old = self.rows.get(identifier)
                if old is not None: self._change(old, -1)
                row = c.execute('SELECT '+ORDER_COLUMNS+' FROM orders WHERE order_id=?', (identifier,)).fetchone()
                if row is None: raise APIError(503, 'QUERY_AUDIT_ORDER_MISSING')
                value = self._row(row); self.rows[identifier] = value; self._change(value, 1); self.delta_rows += 1
        self.revision = revision

    def summary(self, key):
        if key not in self.summaries:
            values = [0, 0, 0, 0]
            for row in self.rows.values():
                if self.match(row, key):
                    values[0] += 1
                    if row[1] == 'active':
                        for i in range(3): values[i+1] += row[i+3]
            self.summaries[key] = values
            while len(self.summaries) > 32: self.summaries.popitem(last=False)
        self.summaries.move_to_end(key); return self.summaries[key]

    def tag(self, value):
        return hmac.new(self.secret, encoded(value).encode(), hashlib.sha256).hexdigest()

    def cursor(self, value):
        raw = encoded(value).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+self.tag(value)

    def decode(self, value):
        try:
            if len(value) > 2048: raise ValueError()
            raw, signature = value.split('.')
            data = json.loads(base64.urlsafe_b64decode(raw+'='*((-len(raw))%4)))
            if type(data) is not dict or not hmac.compare_digest(signature, self.tag(data)): raise ValueError()
            if set(data) != {'format', 'view', 'binding', 'after'} or data['format'] != VERSION or type(data['after']) is not list or len(data['after']) != 2 or any(type(s) is not str for s in data['after']): raise ValueError()
            return data
        except (ValueError, TypeError, UnicodeError, KeyError): raise APIError(422, 'INVALID_CURSOR') from None

    def listing(self, ledger, actor, params):
        if params.keys()-{'offset', 'limit', 'state', 'q', 'cursor', 'view', 'format'} or any(len(v) != 1 for v in params.values()): raise APIError(422, 'INVALID_QUERY')
        get = lambda k, default=None: params.get(k, [default])[0]
        if get('format', VERSION) != VERSION: raise APIError(409, 'QUERY_VERSION_CONFLICT')
        try: offset = int(get('offset', '0')); limit = int(get('limit', '100'))
        except (ValueError, TypeError): raise APIError(422, 'INVALID_QUERY') from None
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 200: raise APIError(422, 'INVALID_QUERY')
        state = get('state'); q = text(get('q', ''), 256).casefold()
        if state not in (None, 'active', 'void') or get('cursor') and offset: raise APIError(422, 'INVALID_QUERY')
        owner = actor.subject if actor.role != 'admin' else None; key = (owner, state, q)
        binding = self.tag({'subject': actor.subject, 'role': actor.role, 'key': key, 'limit': limit})
        with self._lock, ledger.connection(readonly=True) as c:
            c.execute('BEGIN'); revision = verify(c)['revision']; self.synchronize(c, revision)
            view = self.tag({'revision': revision, 'binding': binding})
            cursor = self.decode(get('cursor')) if get('cursor') else None
            if cursor and (cursor['binding'] != binding or cursor['view'] != view) or get('view') and get('view') != view: raise APIError(409, 'QUERY_VIEW_CHANGED')
            clauses = []; values = []
            if owner: clauses.append('owner_id=?'); values.append(owner)
            if state: clauses.append('state=?'); values.append(state)
            if q:
                c.create_function('search_text', 2, search_text, deterministic=True)
                clauses.append('instr(search_text(details_json,order_id),?)>0'); values.append(q)
            if cursor:
                created, identifier = cursor['after']
                clauses.append('(created_at<? OR (created_at=? AND order_id<?))'); values += [created, created, identifier]
            where = ' WHERE '+' AND '.join(clauses) if clauses else ''
            rows = c.execute('SELECT '+ORDER_COLUMNS+' FROM orders'+where+' ORDER BY created_at DESC,order_id DESC LIMIT ? OFFSET ?', (*values, limit+1, offset)).fetchall()
            extra = len(rows) > limit; rows = rows[:limit]; total, income, cost, profit = self.summary(key)
            projected = []
            for row in rows:
                value = {'order_id': row['order_id'], 'revision': row['revision'], 'state': row['state'], 'created_at': row['created_at'], 'details': json.loads(row['details_json']),
                         **financial({k: str(row[k]) for k in ('income_cents', 'cost_cents', 'profit_cents')}, actor)}
                if actor.role == 'admin': value['owner_id'] = row['owner_id']
                projected.append(value)
            next_cursor = self.cursor({'format': VERSION, 'view': view, 'binding': binding, 'after': [rows[-1]['created_at'], rows[-1]['order_id']]}) if extra else None
            value = {'orders': projected, 'offset': offset, 'limit': limit, 'total': total,
                     'totals': financial(dict(zip(('income_cents', 'cost_cents', 'profit_cents'), map(str, (income, cost, profit)))), actor),
                     'format': VERSION, 'view': view, 'next_cursor': next_cursor}
            if actor.role == 'admin': value['ledger_revision'] = revision
            return value
