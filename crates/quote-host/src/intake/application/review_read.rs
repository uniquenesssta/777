//! Bounded access to the immutable three-way basis, including very large orders.
use super::super::{envelope, Intake, FORMAT};
use super::{engine, plan};
use crate::{protocol::fields, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::{application::Order, editing, store};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
pub(super) fn chunk(i: &Intake, data: &Value) -> Result<Value> {
    fields(
        data,
        &["protocol", "operation_id", "section", "offset"],
        &[],
    )?;
    let id = envelope::uuid(&data["operation_id"])?;
    let column = match data["section"].as_str() {
        Some("base") => "base_json",
        Some("current") => "current_json",
        _ => return Err(Error::new(422, "INVALID_FIELDS")),
    };
    let offset = crate::protocol::text(&data["offset"], 19, true)?
        .parse::<usize>()
        .map_err(|_| Error::new(422, "INVALID_FIELDS"))?;
    let c = store::open(&i.ledger, false)?;
    c.execute_batch("BEGIN")?;
    let raw: Option<String> = c
        .query_row(
            &format!("SELECT {column} FROM offline_conflicts WHERE operation_id=?"),
            [id],
            |r| r.get(0),
        )
        .optional()?;
    let reference: Value = serde_json::from_str(&raw.ok_or_else(|| Error::new(404, "NOT_FOUND"))?)?;
    let value = if reference.is_null() {
        Value::Null
    } else {
        let oid = reference["order_id"]
            .as_str()
            .ok_or_else(|| Error::new(503, "LEDGER_UNAVAILABLE"))?;
        let revision = envelope::sequence(&reference["revision"])?;
        let current =
            plan::current(&c, oid)?.ok_or_else(|| Error::new(503, "LEDGER_UNAVAILABLE"))?;
        let snapshot = if current.revision == revision {
            current
        } else {
            let raw: String = c.query_row(
                "SELECT snapshot_json FROM order_versions WHERE order_id=? AND revision=?",
                params![oid, revision],
                |r| r.get(0),
            )?;
            Order::from_snapshot(&editing::validate_archive(&c, oid, revision, &raw)?)?
        };
        if reference.get("sha256").is_some() && engine::reference(Some(&snapshot)) != reference {
            return Err(Error::new(503, "OFFLINE_BASIS_INTEGRITY_CONFLICT"));
        }
        serde_json::to_value(snapshot)?
    };
    let raw = serde_json::to_vec(&value)?;
    if offset > raw.len() {
        return Err(Error::new(422, "INVALID_FIELDS"));
    }
    let end = offset.saturating_add(65536).min(raw.len());
    Ok(
        json!({"protocol":FORMAT,"sha256":store::hash(&raw),"total_bytes":raw.len().to_string(),"offset":offset.to_string(),"data_base64":STANDARD.encode(&raw[offset..end]),"next_offset":if end<raw.len(){json!(end.to_string())}else{Value::Null}}),
    )
}
