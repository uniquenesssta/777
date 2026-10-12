-- Generated structure only; not a production migration/bootstrap script.
-- Authoritative statements: quote_ledger/schema.py
-- ledger-v1, application_id=0x3737374C, schema_version=1

CREATE TABLE ledger_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL, schema_hash TEXT NOT NULL, ledger_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=0), active_price_id TEXT REFERENCES price_versions(price_id)) STRICT;

CREATE TABLE price_versions (price_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, rule_version TEXT NOT NULL, numeric_profile TEXT NOT NULL, published_by TEXT NOT NULL, created_at TEXT NOT NULL) STRICT;

CREATE TABLE requests (request_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, fingerprint TEXT NOT NULL, operation TEXT NOT NULL, result_json TEXT NOT NULL, ledger_revision INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL) STRICT;

CREATE TABLE orders (order_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, price_id TEXT NOT NULL REFERENCES price_versions(price_id), rule_version TEXT NOT NULL, numeric_profile TEXT NOT NULL, input_json TEXT NOT NULL, details_json TEXT NOT NULL, income_cents INTEGER NOT NULL, cost_cents INTEGER NOT NULL, profit_cents INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','void')), revision INTEGER NOT NULL CHECK(revision>0), created_at TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED, CHECK(profit_cents=income_cents-cost_cents AND typeof(income_cents-cost_cents)='integer')) STRICT;

CREATE TABLE lines (line_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), sequence INTEGER NOT NULL CHECK(sequence>0), kind TEXT NOT NULL CHECK(kind IN ('normal','discount')), raw_json TEXT NOT NULL, normalized_json TEXT NOT NULL, price_json TEXT, income_cents INTEGER NOT NULL, cost_cents INTEGER NOT NULL, profit_cents INTEGER NOT NULL, subtotal_before_cents INTEGER NOT NULL, UNIQUE(order_id,sequence), CHECK(profit_cents=income_cents-cost_cents AND typeof(income_cents-cost_cents)='integer')) STRICT;

CREATE TABLE notes (note_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), author_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED) STRICT;

CREATE TABLE import_batches (batch_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, adapter_version TEXT NOT NULL, source_schema TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('staged','committed','rejected')), mapping_json TEXT NOT NULL, report_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_sha256,adapter_version)) STRICT;

CREATE TABLE audit_events (event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id) DEFERRABLE INITIALLY DEFERRED, actor_id TEXT NOT NULL, operation TEXT NOT NULL, order_id TEXT REFERENCES orders(order_id), before_json TEXT, after_json TEXT NOT NULL, created_at TEXT NOT NULL) STRICT;

CREATE INDEX orders_owner_created ON orders(owner_id,created_at,order_id);

CREATE INDEX orders_state_created ON orders(state,created_at,order_id);

CREATE INDEX notes_order_created ON notes(order_id,created_at,note_id);

CREATE INDEX audit_order_created ON audit_events(order_id,created_at,event_id);

CREATE TRIGGER orders_immutable BEFORE UPDATE OF order_id,owner_id,price_id,rule_version,numeric_profile,input_json,details_json,income_cents,cost_cents,profit_cents,created_at,request_id ON orders BEGIN SELECT RAISE(ABORT,'ORDER_SNAPSHOT_IMMUTABLE'); END;

CREATE TRIGGER orders_no_delete BEFORE DELETE ON orders BEGIN SELECT RAISE(ABORT,'ORDER_NO_DELETE'); END;

CREATE TRIGGER price_versions_no_update BEFORE UPDATE ON price_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER price_versions_no_delete BEFORE DELETE ON price_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER lines_no_update BEFORE UPDATE ON lines BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER lines_no_delete BEFORE DELETE ON lines BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER notes_no_update BEFORE UPDATE ON notes BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER notes_no_delete BEFORE DELETE ON notes BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER requests_no_update BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER requests_no_delete BEFORE DELETE ON requests BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;

CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
