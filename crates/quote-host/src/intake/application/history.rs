//! Business history chunks obey the same current owner/finance scope as orders.
use super::super::{context::Context, envelope, Intake, FORMAT};
use crate::{automatic::permissions, protocol, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::store;
use serde_json::{json, Value};
pub(super) fn chunk(i: &Intake, ctx: &Context, data: &Value) -> Result<Value> {
    protocol::fields(
        data,
        &["protocol", "epoch", "order_id", "revision", "offset"],
        &[],
    )?;
    if data["epoch"] != i.config["epoch"] {
        return Err(Error::new(409, "OFFLINE_CURSOR_REBUILD_REQUIRED"));
    }
    let id = envelope::uuid(&data["order_id"])?;
    let revision = envelope::sequence(&data["revision"])?;
    let offset = protocol::text(&data["offset"], 19, true)?
        .parse::<usize>()
        .map_err(|_| Error::new(422, "INVALID_FIELDS"))?;
    let c = store::open(&i.ledger, false)?;
    c.execute_batch("BEGIN")?;
    let mut value = crate::order_changes::read(&c, &ctx.actor, id, revision)?;
    if !ctx.capabilities.iter().any(|v| v == "finance") {
        permissions::redact(&mut value);
    }
    let raw = serde_json::to_vec(&value)?;
    if offset > raw.len() {
        return Err(Error::new(422, "INVALID_FIELDS"));
    }
    let end = offset.saturating_add(65536).min(raw.len());
    Ok(
        json!({"protocol":FORMAT,"sha256":store::hash(&raw),"offset":offset.to_string(),"total_bytes":raw.len().to_string(),"data_base64":STANDARD.encode(&raw[offset..end]),"next_offset":if end<raw.len(){json!(end.to_string())}else{Value::Null}}),
    )
}
