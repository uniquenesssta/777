//! Durable deletion markers reuse the immutable journal; business snapshots remain auditable.
use crate::{editing, journal, store::*, Error, Result};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
pub const VISIBLE: &str = "NOT EXISTS(SELECT 1 FROM audit_events deletion WHERE deletion.order_id=orders.order_id AND deletion.operation='delete_order')";
pub fn deleted(c: &Connection, order: &str) -> Result<bool> {
    Ok(c.query_row(
        "SELECT EXISTS(SELECT 1 FROM audit_events WHERE order_id=? AND operation='delete_order')",
        [order],
        |r| r.get(0),
    )?)
}
pub fn available(c: &Connection, order: &str) -> Result<()> {
    if deleted(c, order)? {
        return Err(Error::new("ORDER_DELETED"));
    }
    Ok(())
}
pub fn delete(
    c: &mut Connection,
    actor: &Actor,
    request: &str,
    order: &str,
    expected: i64,
    reason: &str,
) -> Result<Value> {
    actor.admin()?;
    id(request)?;
    id(order)?;
    text(reason, 512, true)?;
    if expected < 1 {
        return Err(Error::new("VALIDATION"));
    }
    let fingerprint = hash(encoded(
        &json!({"actor":actor,"operation":"delete_order","order_id":order,"expected_revision":expected,"reason":reason}),
    ));
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let old: Option<(String, String)> = tx
        .query_row(
            "SELECT fingerprint,result_json FROM requests WHERE request_id=?",
            [request],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((prior, raw)) = old {
        if prior != fingerprint {
            return Err(Error::new("CONFLICT"));
        }
        return Ok(serde_json::from_str(&raw)?);
    }
    available(&tx, order)?;
    let before = editing::owned(&tx, actor, order)?;
    if before["order"]["revision"] != expected {
        return Err(Error::new("CONFLICT"));
    }
    let next = expected
        .checked_add(1)
        .ok_or_else(|| Error::new("REVISION_CAPACITY"))?;
    editing::archive(&tx, actor, &before)?;
    tx.execute(
        "UPDATE orders SET state='void',revision=? WHERE order_id=?",
        params![next, order],
    )?;
    let result = journal::record(
        &tx,
        journal::Change {
            request_id: request,
            actor,
            operation: "delete_order",
            fingerprint: &fingerprint,
            result: json!({"order_id":order,"revision":next,"deleted":true,"reason":reason}),
            order_id: Some(order),
            before: &before,
        },
    )?;
    tx.commit().map_err(|_| Error::new("COMMIT_UNKNOWN"))?;
    Ok(result)
}
