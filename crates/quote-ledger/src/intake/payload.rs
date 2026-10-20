//! Shared closed offline business payload contract, used before local and Host commits.
use crate::{Error, Result};
use serde_json::Value;
fn fields(v: &Value, required: &[&str], optional: &[&str]) -> Result<()> {
    let m = v.as_object().ok_or_else(|| Error::new("INVALID_FIELDS"))?;
    if required.iter().any(|k| !m.contains_key(*k))
        || m.keys()
            .any(|k| !required.contains(&k.as_str()) && !optional.contains(&k.as_str()))
    {
        return Err(Error::new("INVALID_FIELDS"));
    }
    Ok(())
}
fn text(v: &Value, max: usize, required: bool) -> Result<&str> {
    let s = v.as_str().ok_or_else(|| Error::new("INVALID_TEXT"))?;
    if s.chars().count() > max
        || s.contains('\0')
        || required && quote_core::numbers::trim(s).is_empty()
    {
        return Err(Error::new("INVALID_TEXT"));
    }
    Ok(s)
}
fn uuid(v: &Value) -> Result<&str> {
    let s = text(v, 36, true)?;
    crate::store::id(s)?;
    Ok(s)
}
fn raw(v: &Value) -> Result<()> {
    match v["line_kind"].as_str() {
        Some("normal") => {
            fields(v, &["line_kind", "product_id", "q"], &["h", "w", "name"])?;
            for k in ["product_id", "q", "h", "w", "name"] {
                if let Some(value) = v.get(k) {
                    text(value, 256, false)?;
                }
            }
        }
        Some("discount") => {
            fields(v, &["line_kind", "percent"], &["name"])?;
            text(&v["percent"], 256, true)?;
            if let Some(name) = v.get("name") {
                text(name, 256, false)?;
            }
        }
        _ => return Err(Error::new("OFFLINE_LINE_INVALID")),
    }
    Ok(())
}
fn customer(v: &Value) -> Result<()> {
    let m = v
        .as_object()
        .ok_or_else(|| Error::new("OFFLINE_CUSTOMER_INVALID"))?;
    if m.len() > 1 {
        return Err(Error::new("OFFLINE_CUSTOMER_INVALID"));
    }
    for (k, v) in m {
        match k.as_str() {
            "new_customer" if v == true => (),
            "customer_id" | "anchor_order_id" => {
                uuid(v)?;
            }
            _ => return Err(Error::new("OFFLINE_CUSTOMER_INVALID")),
        }
    }
    Ok(())
}
pub fn validate(v: &Value) -> Result<()> {
    let p = &v["payload"];
    match v["kind"].as_str() {
        Some("create") => {
            fields(p, &["snapshot", "details", "customer"], &[])?;
            customer(&p["customer"])?;
            fields(&p["details"], &["customer", "order_ref", "wechat"], &[])?;
            for k in ["customer", "order_ref", "wechat"] {
                text(&p["details"][k], 256, false)?;
            }
            fields(&p["snapshot"], &["price_version_id", "lines"], &[])?;
            text(&p["snapshot"]["price_version_id"], 256, true)?;
            let lines = p["snapshot"]["lines"]
                .as_array()
                .ok_or_else(|| Error::new("OFFLINE_LINE_INVALID"))?;
            let mut ids = std::collections::HashSet::new();
            for l in lines {
                fields(l, &["line_id", "raw"], &[])?;
                if !ids.insert(uuid(&l["line_id"])?) {
                    return Err(Error::new("OFFLINE_LINE_ID_CONFLICT"));
                }
                raw(&l["raw"])?;
            }
        }
        Some("edit") => {
            fields(p, &["detail_changes", "line_changes", "customer"], &[])?;
            customer(&p["customer"])?;
            fields(
                &p["detail_changes"],
                &[],
                &["customer", "order_ref", "wechat"],
            )?;
            for v in p["detail_changes"].as_object().unwrap().values() {
                text(v, 256, false)?;
            }
            let mut ids = std::collections::HashSet::new();
            for l in p["line_changes"]
                .as_array()
                .ok_or_else(|| Error::new("OFFLINE_LINE_INVALID"))?
            {
                if l["op"] == "remove" {
                    fields(l, &["op", "line_id"], &[])?;
                } else {
                    fields(l, &["op", "line_id", "raw"], &[])?;
                    raw(&l["raw"])?;
                }
                if !["add", "replace", "remove"].contains(&text(&l["op"], 16, true)?)
                    || !ids.insert(uuid(&l["line_id"])?)
                {
                    return Err(Error::new("OFFLINE_LINE_INVALID"));
                }
            }
        }
        Some("append_note") => {
            fields(p, &["note_id", "body"], &[])?;
            uuid(&p["note_id"])?;
            text(&p["body"], 4096, false)?;
        }
        Some("set_state") => {
            fields(p, &["state", "reason"], &[])?;
            if !["active", "void"].contains(&text(&p["state"], 16, true)?) {
                return Err(Error::new("OFFLINE_STATE_INVALID"));
            }
            text(&p["reason"], 4096, true)?;
        }
        _ => return Err(Error::new("OFFLINE_KIND_INVALID")),
    }
    Ok(())
}
