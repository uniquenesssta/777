//! Canonical, float-free wire envelopes. External references never determine identity.
use super::*;
use crate::protocol::{fields, text};
use serde_json::{json, Value};
pub fn canonical(v: &Value) -> Result<Vec<u8>> {
    quote_ledger::intake::canonical::encode(v).map_err(|e| Error::new(422, &e.code))
}

pub fn digest(v: &Value) -> Result<String> {
    let mut v = v.clone();
    v.as_object_mut()
        .ok_or_else(|| Error::new(422, "OFFLINE_OPERATION_INVALID"))?
        .remove("content_sha256");
    let mut raw = format!("{FORMAT}\n").into_bytes();
    raw.extend(canonical(&v)?);
    Ok(store::hash(raw))
}
pub fn uuid(v: &Value) -> Result<&str> {
    let s = text(v, 36, true)?;
    store::id(s)?;
    Ok(s)
}
pub fn sequence(v: &Value) -> Result<i64> {
    let s = text(v, 19, true)?;
    if s.starts_with('0') || !s.bytes().all(|b| b.is_ascii_digit()) {
        return Err(Error::new(422, "OFFLINE_SEQUENCE_INVALID"));
    }
    s.parse::<i64>()
        .ok()
        .filter(|n| *n > 0)
        .ok_or_else(|| Error::new(422, "OFFLINE_SEQUENCE_INVALID"))
}
pub fn validate(v: &Value) -> Result<()> {
    fields(
        v,
        &[
            "protocol",
            "site_id",
            "ledger_id",
            "device_id",
            "stream_id",
            "owner_id",
            "lease_id",
            "operation_id",
            "device_sequence",
            "order_id",
            "kind",
            "base",
            "created_at",
            "rule_version",
            "numeric_profile",
            "payload",
            "content_sha256",
        ],
        &[],
    )?;
    if canonical(v)?.len() > 262144 {
        return Err(Error::new(413, "OFFLINE_OPERATION_TOO_LARGE"));
    }
    if v["protocol"] != FORMAT {
        return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
    }
    for k in [
        "site_id",
        "ledger_id",
        "device_id",
        "stream_id",
        "owner_id",
        "lease_id",
        "operation_id",
        "order_id",
    ] {
        uuid(&v[k])?;
    }
    sequence(&v["device_sequence"])?;
    text(&v["rule_version"], 256, true)?;
    text(&v["numeric_profile"], 256, true)?;
    if digest(v)? != v["content_sha256"] {
        return Err(Error::new(409, "OFFLINE_CONTENT_DIGEST_CONFLICT"));
    }
    fields(
        &v["base"],
        &["order_revision", "previous_operation_id"],
        &[],
    )?;
    if !v["base"]["order_revision"].is_null() {
        sequence(&v["base"]["order_revision"])?;
    }
    if !v["base"]["previous_operation_id"].is_null() {
        uuid(&v["base"]["previous_operation_id"])?;
    }
    let at = text(&v["created_at"], 27, true)?;
    let parsed = time::OffsetDateTime::parse(at, &time::format_description::well_known::Rfc3339)
        .map_err(|_| Error::new(422, "OFFLINE_TIME_INVALID"))?;
    if at.len() != 27 || !at.ends_with('Z') || parsed.offset() != time::UtcOffset::UTC {
        return Err(Error::new(422, "OFFLINE_TIME_INVALID"));
    }
    if v["kind"] == "create" {
        if v["base"] != json!({"order_revision":null,"previous_operation_id":null}) {
            return Err(Error::new(422, "OFFLINE_BASE_INVALID"));
        }
    } else if v["base"]["order_revision"].is_null() && v["base"]["previous_operation_id"].is_null()
    {
        return Err(Error::new(422, "OFFLINE_BASE_INVALID"));
    }
    if v["base"]["previous_operation_id"] == v["operation_id"] {
        return Err(Error::new(422, "OFFLINE_DEPENDENCY_CYCLE"));
    }
    super::payload::validate(v)
}
