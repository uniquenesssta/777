//! Local export history and immutable input snapshots, isolated by ledger connection.
use super::*;
use rusqlite::{params, Connection, OptionalExtension};
fn err() -> DesktopError {
    DesktopError::new(503, "LOCAL_OUTPUT_HISTORY_UNAVAILABLE")
}
fn db(store: &Store) -> Result<Connection> {
    let path = PathBuf::from(store.profile()).join("local-exports.sqlite3");
    if path.exists() {
        crate::journal::check(&path)?;
    }
    let c = Connection::open(path).map_err(|_| err())?;
    c.execute_batch("CREATE TABLE IF NOT EXISTS jobs(scope TEXT NOT NULL,id TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(scope,id));").map_err(|_|err())?;
    Ok(c)
}
pub(crate) fn insert(store: &Store, scope: &str, payload: &Value) -> Result<Value> {
    if payload.to_string().len() > 2 * 1024 * 1024 {
        return Err(DesktopError::new(413, "OUTPUT_SNAPSHOT_TOO_LARGE"));
    }
    let id = payload["job_id"].as_str().ok_or_else(err)?;
    crate::types::identifier(id)?;
    store.write(&format!("local-export-{id}.bin"), payload)?;
    let job = json!({"job_id":id,"order_id":payload["order"]["order_id"],"order_ref":payload["order"]["details"]["order_ref"],"kind":payload["kind"],"state":"queued","created_at":payload["generated_at"],"batch":payload["batch"],"range":payload["range"]});
    db(store)?
        .execute(
            "INSERT INTO jobs VALUES(?,?,?)",
            params![scope, id, job.to_string()],
        )
        .map_err(|_| err())?;
    Ok(job)
}
pub(crate) fn get(store: &Store, scope: &str, id: &str) -> Result<Value> {
    crate::types::identifier(id)?;
    let raw: Option<String> = db(store)?
        .query_row(
            "SELECT record FROM jobs WHERE scope=? AND id=?",
            params![scope, id],
            |r| r.get(0),
        )
        .optional()
        .map_err(|_| err())?;
    serde_json::from_str(&raw.ok_or_else(|| DesktopError::new(404, "NOT_FOUND"))?)
        .map_err(|_| err())
}
pub(crate) fn update(store: &Store, scope: &str, job: &Value) -> Result<()> {
    db(store)?
        .execute(
            "UPDATE jobs SET record=? WHERE scope=? AND id=?",
            params![job.to_string(), scope, job["job_id"].as_str()],
        )
        .map_err(|_| err())?;
    Ok(())
}
pub(crate) fn list(store: &Store, scope: &str, offset: u32) -> Result<Value> {
    let c = db(store)?;
    let total: i64 = c
        .query_row(
            "SELECT count(*) FROM jobs WHERE scope=? AND json_extract(record,'$.deleted') IS NULL",
            [scope],
            |r| r.get(0),
        )
        .map_err(|_| err())?;
    let mut q=c.prepare("SELECT record FROM jobs WHERE scope=? AND json_extract(record,'$.deleted') IS NULL ORDER BY rowid DESC LIMIT 100 OFFSET ?").map_err(|_|err())?;
    let raw = q
        .query_map(params![scope, offset], |r| r.get::<_, String>(0))
        .map_err(|_| err())?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(|_| err())?;
    let jobs = raw
        .into_iter()
        .map(|s| {
            let mut job: Value = serde_json::from_str(&s).map_err(|_| err())?;
            if job.get("order_ref").is_none() && job["kind"] != "excel_period" {
                let snapshot = payload(store, job["job_id"].as_str().ok_or_else(err)?)?;
                job["order_ref"] = snapshot["order"]["details"]["order_ref"].clone();
            }
            Ok(job)
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({"jobs":jobs,"offset":offset,"total":total,"limit":100}))
}
pub(crate) fn payload(store: &Store, id: &str) -> Result<Value> {
    crate::types::identifier(id)?;
    store
        .read(&format!("local-export-{id}.bin"))?
        .ok_or_else(err)
}
