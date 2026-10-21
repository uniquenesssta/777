//! Fixed-site, scoped installation authorization. Secrets never enter diagnostics.
pub mod api;
pub mod bootstrap;
pub mod business;
mod capacity;
pub mod deployment;
pub mod devices;
pub mod installation;
pub mod issuance;
pub mod issuer_state;
pub mod kit;
pub mod legacy_device;
pub mod local_issuer;
pub mod nodes;
pub mod packages;
pub mod pairing;
pub mod permissions;
pub mod registration;
pub mod schema;
pub mod sessions;
pub mod trust;
pub mod upgrade;
use crate::{auth, fail, files, Error, Result};
use quote_ledger::store;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use subtle::ConstantTimeEq;
pub const ISSUANCE: &str = "777-package-issuance-v1";
pub const ENROLLMENT: &str = "777-auto-enrollment-v1";
pub const SCOPED_AUTH: &str = "777-scoped-auth-v1";
pub fn secret() -> Result<String> {
    crate::cluster::membership::credential()
}
pub fn digest(value: &str) -> Result<String> {
    crate::cluster::membership::validate_secret(value)?;
    Ok(store::hash(value))
}
pub fn matches(expected: &str, raw: &str) -> bool {
    digest(raw).is_ok_and(|v| expected.as_bytes().ct_eq(v.as_bytes()).unwrap_u8() == 1)
}
pub fn id(v: &Value, key: &str) -> Result<String> {
    let s = crate::protocol::text(&v[key], 36, true)?;
    store::id(s)?;
    Ok(s.into())
}
pub fn hex(v: &Value, key: &str) -> Result<String> {
    let s = crate::protocol::text(&v[key], 64, true)?;
    if !crate::cluster::snapshot::hex(s) {
        return fail(422, "AUTOMATIC_DIGEST_INVALID");
    }
    Ok(s.into())
}
pub fn envelope(v: &Value, protocol: &str, extra: &[&str]) -> Result<String> {
    let mut keys = vec!["protocol", "request_id"];
    keys.extend(extra);
    crate::protocol::fields(v, &keys, &[])?;
    if v["protocol"] != protocol {
        return fail(426, "PROTOCOL_UPGRADE_REQUIRED");
    }
    id(v, "request_id")
}
pub fn audit(c: &Connection, actor: &str, op: &str, target: &str) -> Result<()> {
    c.execute(
        "INSERT INTO automatic_audit(actor,operation,target,at) VALUES(?,?,?,?)",
        params![actor, op, target, auth::now()],
    )?;
    Ok(())
}
pub fn receipt(c: &Connection, scope: &str, request: &str, data: &Value) -> Result<Option<Value>> {
    let row:Option<(String,String)>=c.query_row("SELECT fingerprint,response_json FROM automatic_receipts WHERE scope=? AND request_id=?",params![scope,request],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
    match row {
        Some((fp, raw)) if fp == store::hash(store::encoded(data)) => {
            Ok(Some(serde_json::from_str(&raw)?))
        }
        Some(_) => fail(409, "AUTOMATIC_REQUEST_CONFLICT"),
        None => Ok(None),
    }
}
pub fn remember(
    c: &Connection,
    scope: &str,
    request: &str,
    data: &Value,
    response: &Value,
) -> Result<()> {
    c.execute(
        "INSERT INTO automatic_receipts VALUES(?,?,?,?)",
        params![
            scope,
            request,
            store::hash(store::encoded(data)),
            store::encoded(response)
        ],
    )?;
    Ok(())
}
pub fn binding(c: &Connection, data: &Value) -> Result<Value> {
    let p = trust::profile(c)?;
    if data["site_id"] != p["site_id"] || data["ledger_id"] != p["ledger_id"] {
        return fail(409, "AUTOMATIC_SITE_CONFLICT");
    }
    Ok(p)
}
pub fn capabilities(c: &Connection) -> Result<Value> {
    let p = trust::profile(c)?;
    Ok(json!({"site_id":p["site_id"],"ledger_id":p["ledger_id"],"protocols":trust::protocols()}))
}
pub fn denied() -> Error {
    Error::new(403, "AUTOMATIC_AUTHORIZATION_DENIED")
}
