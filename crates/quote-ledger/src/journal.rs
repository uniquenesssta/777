//! Shared transaction-local financial receipt, audit and change-feed recording.
use crate::{store::*, Error, Result};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
pub struct Change<'a> {
    pub request_id: &'a str,
    pub actor: &'a Actor,
    pub operation: &'a str,
    pub fingerprint: &'a str,
    pub result: Value,
    pub order_id: Option<&'a str>,
    pub before: &'a Value,
}
pub fn record(c: &Connection, change: Change<'_>) -> Result<Value> {
    if c.is_autocommit() {
        return Err(Error::new("TRANSACTION_REQUIRED"));
    }
    let meta = verify(c)?;
    let revision = meta["revision"]
        .as_i64()
        .and_then(|v| v.checked_add(1))
        .ok_or_else(|| Error::new("REVISION_CAPACITY"))?;
    let Change {
        request_id,
        actor,
        operation,
        fingerprint,
        mut result,
        order_id,
        before,
    } = change;
    result["request_id"] = json!(request_id);
    result["ledger_revision"] = json!(revision);
    c.execute(
        "INSERT INTO requests VALUES(?,?,?,?,?,?,?)",
        params![
            request_id,
            actor.subject,
            fingerprint,
            operation,
            encoded(&result),
            revision,
            now()
        ],
    )?;
    c.execute(
        "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?)",
        params![
            uid()?,
            request_id,
            actor.subject,
            operation,
            order_id,
            if before.is_null() {
                None
            } else {
                Some(encoded(before))
            },
            encoded(&result),
            now()
        ],
    )?;
    c.execute(
        "UPDATE ledger_meta SET revision=? WHERE singleton=1",
        [revision],
    )?;
    if meta["schema_version"] == 3 {
        if let Some(id) = order_id {
            c.execute("INSERT INTO order_changes_feed(order_id,order_revision,owner_id,created_at) SELECT order_id,revision,owner_id,? FROM orders WHERE order_id=?",params![time::OffsetDateTime::now_utc().unix_timestamp(),id])?;
        }
    }
    Ok(result)
}
