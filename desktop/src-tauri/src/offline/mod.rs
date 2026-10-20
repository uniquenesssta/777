//! Per-device durable business views and immutable upload originals. No Host replica files.
#[cfg(test)]
mod checks;
mod commands;
mod db;
mod history;
mod history_queue;
mod orders;
mod pricing;
mod projection;
mod queries;
mod queue;
mod trust;
mod witness;
mod worker;
use crate::{DesktopError, Result};
pub(crate) use db::Local;
use serde_json::{json, Value};
pub(crate) use trust::Binding;
fn fault(code: &str) -> DesktopError {
    DesktopError::new(409, code)
}
fn sql(_: rusqlite::Error) -> DesktopError {
    DesktopError::new(503, "LOCAL_ORDERS_UNAVAILABLE")
}
fn json_error(_: serde_json::Error) -> DesktopError {
    fault("LOCAL_DATA_INVALID")
}
fn canonical(v: &Value) -> Result<Vec<u8>> {
    quote_ledger::intake::canonical::encode(v).map_err(|_| fault("LOCAL_WIRE_INVALID"))
}
fn digest(domain: &str, v: &Value) -> Result<String> {
    use sha2::{Digest, Sha256};
    Ok(format!(
        "{:x}",
        Sha256::digest([domain.as_bytes(), b"\n", &canonical(v)?].concat())
    ))
}
pub(crate) fn now() -> i64 {
    time::OffsetDateTime::now_utc().unix_timestamp()
}
fn stamp() -> String {
    time::OffsetDateTime::now_utc()
        .format(
            &time::format_description::parse(
                "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z",
            )
            .unwrap(),
        )
        .unwrap()
}
fn number(v: &Value) -> Result<i64> {
    v.as_str()
        .and_then(|s| s.parse().ok())
        .filter(|n| *n >= 0)
        .ok_or_else(|| fault("LOCAL_VERSION_INVALID"))
}
fn identifier(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| quote_security::automatic::uuid(s))
        .ok_or_else(|| fault("LOCAL_ID_INVALID"))
}
fn permit(ctx: &Value, cap: &str) -> Result<()> {
    if ctx["lease"]["body"]["capabilities"]
        .as_array()
        .is_some_and(|a| a.iter().any(|v| v == cap))
    {
        Ok(())
    } else {
        Err(DesktopError::new(403, "PACKAGE_PERMISSION_DENIED"))
    }
}
pub(crate) fn public(v: &mut Value, ctx: &Value) {
    if permit(ctx, "finance").is_err() {
        crate::permissions::redact_financial(v)
    }
}
