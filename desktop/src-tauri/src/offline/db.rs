use super::*;
use rusqlite::{params, Connection, OptionalExtension};
use std::path::PathBuf;
pub(crate) struct Local {
    pub(super) c: Connection,
    pub(super) auxiliary: bool,
    pub(super) witness: PathBuf,
    pub(super) transport: PathBuf,
}
impl Local {
    pub(crate) fn open(path: PathBuf, auxiliary: bool) -> Result<Self> {
        let witness = path.with_file_name("offline-high-water.bin");
        let transport = path.with_file_name("offline-transport.sqlite3");
        let c = Connection::open(path).map_err(sql)?;
        let version: i64 = c
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .map_err(sql)?;
        let tables: i64 = c
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'",
                [],
                |r| r.get(0),
            )
            .map_err(sql)?;
        if version != 1 && (version != 0 || tables != 0) {
            return Err(fault("LOCAL_SCHEMA_UNSUPPORTED"));
        }
        c.busy_timeout(std::time::Duration::from_millis(500))
            .map_err(sql)?;
        c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON; PRAGMA max_page_count=524288; PRAGMA journal_size_limit=67108864; BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS local_meta(key TEXT PRIMARY KEY,value BLOB NOT NULL) STRICT;
        CREATE TABLE IF NOT EXISTS local_commands(id TEXT PRIMARY KEY,subject TEXT NOT NULL,body BLOB NOT NULL,receipt BLOB NOT NULL) STRICT;
        CREATE TABLE IF NOT EXISTS local_orders(id TEXT PRIMARY KEY,confirmed BLOB,working BLOB NOT NULL,revision INTEGER NOT NULL,last_operation TEXT) STRICT;
        CREATE TABLE IF NOT EXISTS local_operations(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,stream TEXT NOT NULL,sequence INTEGER NOT NULL,raw BLOB NOT NULL,state TEXT NOT NULL,receipt BLOB,previous_id TEXT,anchor_id TEXT,UNIQUE(stream,sequence)) STRICT;
        CREATE INDEX IF NOT EXISTS local_pending ON local_operations(state,sequence);
        CREATE TABLE IF NOT EXISTS local_diff_queue(order_id TEXT NOT NULL,revision TEXT NOT NULL,PRIMARY KEY(order_id,revision)) STRICT;
        CREATE TABLE IF NOT EXISTS local_diff_parts(order_id TEXT NOT NULL,revision TEXT NOT NULL,offset INTEGER NOT NULL,body BLOB NOT NULL,PRIMARY KEY(order_id,revision,offset)) STRICT;
        CREATE TABLE IF NOT EXISTS local_history(order_id TEXT NOT NULL,revision INTEGER NOT NULL,before BLOB NOT NULL,after BLOB NOT NULL,PRIMARY KEY(order_id,revision)) STRICT; PRAGMA user_version=1; COMMIT;").map_err(sql)?;
        Ok(Self {
            c,
            auxiliary,
            witness,
            transport,
        })
    }
    pub(super) fn encode(&self, value: &Value) -> Result<Vec<u8>> {
        let raw = serde_json::to_vec(value).map_err(json_error)?;
        quote_security::protect::protect(&raw, true, self.auxiliary)
            .map_err(|_| fault("LOCAL_PROTECTION_FAILED"))
    }
    pub(super) fn decode(&self, value: &[u8]) -> Result<Value> {
        let raw = quote_security::protect::protect(value, false, self.auxiliary)
            .map_err(|_| fault("LOCAL_PROTECTION_FAILED"))?;
        serde_json::from_slice(&raw).map_err(json_error)
    }
    pub(crate) fn meta(&self, key: &str) -> Result<Option<Value>> {
        self.c
            .query_row("SELECT value FROM local_meta WHERE key=?", [key], |r| {
                r.get::<_, Vec<u8>>(0)
            })
            .optional()
            .map_err(sql)?
            .map(|v| self.decode(&v))
            .transpose()
    }
    pub(crate) fn put(&self, key: &str, value: &Value) -> Result<()> {
        self.c.execute("INSERT INTO local_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",params![key,self.encode(value)?]).map_err(sql)?;
        Ok(())
    }
    pub(crate) fn active(&self) -> Result<bool> {
        Ok(self.meta("context")?.is_some())
    }
    pub(super) fn transaction<T>(&self, work: impl FnOnce() -> Result<T>) -> Result<T> {
        self.c.execute_batch("BEGIN IMMEDIATE").map_err(sql)?;
        match work() {
            Ok(v) => {
                if let Err(e) = self.c.execute_batch("COMMIT") {
                    let _ = self.c.execute_batch("ROLLBACK");
                    return Err(sql(e));
                }
                Ok(v)
            }
            Err(e) => {
                let _ = self.c.execute_batch("ROLLBACK");
                Err(e)
            }
        }
    }
}
