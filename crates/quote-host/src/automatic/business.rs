//! One guard around all existing business early returns, including output receipts.
use super::*;
use crate::service::Service;
pub fn context(s: &Service, token: &str) -> Result<Option<sessions::Context>> {
    if !token.starts_with("a2.") {
        return Ok(None);
    }
    let c = s.auth.connection()?;
    if !schema::enabled(&c)? {
        return Err(denied());
    }
    let ctx = sessions::lookup(&c, token)?;
    if ctx.kind != "device" {
        return Err(denied());
    }
    Ok(Some(ctx))
}
pub fn response(s: &Service, caps: &[String], path: &str, mut value: Value) -> Result<Value> {
    if path.starts_with("/v1/requests/") {
        if let Some(id) = value["result"]["job_id"].as_str() {
            permissions::authorize(s, caps, "GET", &format!("/v1/outputs/{id}"), &Value::Null)?;
        } else if !value["result"].is_null() {
            // Pending mutations remain discoverable, but only through a business capability.
            permissions::require(caps, "quote")?;
        }
    }
    if !caps.iter().any(|v| v == "finance") {
        permissions::redact(&mut value)
    }
    if path == "/v1/backup" {
        sanitize_backup(&mut value)
    }
    Ok(value)
}
fn sanitize_backup(v: &mut Value) {
    match v {
        Value::Object(m) => {
            m.retain(|k, _| {
                ![
                    "target",
                    "hidden_dir",
                    "hidden_destination",
                    "backup_dir",
                    "path",
                    "directory",
                    "root",
                ]
                .contains(&k.as_str())
            });
            for (k, v) in m.iter_mut() {
                if k.contains("path") || k.contains("target") || k.contains("directory") {
                    *v = Value::Null;
                } else {
                    sanitize_backup(v)
                }
            }
        }
        Value::Array(a) => a.iter_mut().for_each(sanitize_backup),
        Value::String(s) if s.contains("192.168.4.23") || s.contains('\\') || s.contains(":/") => {
            *v = Value::Null
        }
        _ => (),
    }
}
