"""ledger-v1: host-local, versioned SQL shared with the future Rust adapter."""
import hashlib
import json
import sqlite3
from contextlib import closing
from functools import lru_cache

VERSION = 1
APPLICATION_ID = 0x3737374C
DDL = (
'''CREATE TABLE ledger_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL, schema_hash TEXT NOT NULL, ledger_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=0), active_price_id TEXT REFERENCES price_versions(price_id)) STRICT''',
'''CREATE TABLE price_versions (price_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, rule_version TEXT NOT NULL, numeric_profile TEXT NOT NULL, published_by TEXT NOT NULL, created_at TEXT NOT NULL) STRICT''',
'''CREATE TABLE requests (request_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, fingerprint TEXT NOT NULL, operation TEXT NOT NULL, result_json TEXT NOT NULL, ledger_revision INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL) STRICT''',
'''CREATE TABLE orders (order_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, price_id TEXT NOT NULL REFERENCES price_versions(price_id), rule_version TEXT NOT NULL, numeric_profile TEXT NOT NULL, input_json TEXT NOT NULL, details_json TEXT NOT NULL, income_cents INTEGER NOT NULL, cost_cents INTEGER NOT NULL, profit_cents INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','void')), revision INTEGER NOT NULL CHECK(revision>0), created_at TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED, CHECK(profit_cents=income_cents-cost_cents AND typeof(income_cents-cost_cents)='integer')) STRICT''',
'''CREATE TABLE lines (line_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), sequence INTEGER NOT NULL CHECK(sequence>0), kind TEXT NOT NULL CHECK(kind IN ('normal','discount')), raw_json TEXT NOT NULL, normalized_json TEXT NOT NULL, price_json TEXT, income_cents INTEGER NOT NULL, cost_cents INTEGER NOT NULL, profit_cents INTEGER NOT NULL, subtotal_before_cents INTEGER NOT NULL, UNIQUE(order_id,sequence), CHECK(profit_cents=income_cents-cost_cents AND typeof(income_cents-cost_cents)='integer')) STRICT''',
'''CREATE TABLE notes (note_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), author_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED) STRICT''',
'''CREATE TABLE import_batches (batch_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, adapter_version TEXT NOT NULL, source_schema TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('staged','committed','rejected')), mapping_json TEXT NOT NULL, report_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_sha256,adapter_version)) STRICT''',
'''CREATE TABLE audit_events (event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED, actor_id TEXT NOT NULL, operation TEXT NOT NULL, order_id TEXT REFERENCES orders(order_id), before_json TEXT, after_json TEXT NOT NULL, created_at TEXT NOT NULL) STRICT''',
'''CREATE INDEX orders_owner_created ON orders(owner_id,created_at,order_id)''',
'''CREATE INDEX orders_state_created ON orders(state,created_at,order_id)''',
'''CREATE INDEX notes_order_created ON notes(order_id,created_at,note_id)''',
'''CREATE INDEX audit_order_created ON audit_events(order_id,created_at,event_id)''',
'''CREATE TRIGGER orders_immutable BEFORE UPDATE OF order_id,owner_id,price_id,rule_version,numeric_profile,input_json,details_json,income_cents,cost_cents,profit_cents,created_at,request_id ON orders BEGIN SELECT RAISE(ABORT,'ORDER_SNAPSHOT_IMMUTABLE'); END''',
'''CREATE TRIGGER orders_no_delete BEFORE DELETE ON orders BEGIN SELECT RAISE(ABORT,'ORDER_NO_DELETE'); END''',
)
for table in ('price_versions','lines','notes','requests','audit_events'):
    DDL += tuple(f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END" for op in ('UPDATE','DELETE'))


def signature(connection):
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    # Ordered arrays + compact UTF-8 JSON can be reproduced by Rust directly.
    canonical=json.dumps([list(row) for row in rows],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


@lru_cache(maxsize=1)
def expected_hash():
    with closing(sqlite3.connect(':memory:')) as connection:
        for sql in DDL:connection.execute(sql)
        return signature(connection)
