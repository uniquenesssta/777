//! Authenticated operator settings for the connected Host, serialized with its backup worker.
mod directories;
use crate::{
    auth::Auth, backup, daily_backup, fail, files, protocol, service::Service, Error, Result,
};
use quote_ledger::store;
use serde_json::{json, Value};
use std::path::Path;

pub fn read(s: &Service) -> Result<Value> {
    let daily = daily_backup::config(s)?;
    let mut value = json!({"ledger_id":s.config["ledger_id"],"backup_dir":s.config["backup_dir"],
        "hidden_dir":daily["hidden_dir"],"daily_hour":daily["daily_hour"],"timezone":"Asia/Shanghai"});
    value["revision"] = json!(store::hash(serde_json::to_vec(&value)?));
    Ok(value)
}
pub fn handle(
    s: &mut Service,
    method: &str,
    path: &str,
    token: &str,
    data: &Value,
) -> Result<Value> {
    // Only administrator login sessions; automatic/legacy device credentials cannot maintain Host paths.
    let actor = s.auth.authenticate(token)?;
    Auth::admin(&actor)?;
    match (method, path) {
        ("GET", "/v1/developer/backup-settings") => read(s),
        ("POST", "/v1/developer/backup-directories") => {
            protocol::fields(data, &["ledger_id", "path"], &[])?;
            identity(s, data)?;
            directories::list(s, protocol::text(&data["path"], 4096, false)?)
        }
        ("POST", "/v1/developer/backup-settings") => {
            protocol::fields(
                data,
                &["ledger_id", "expected_revision", "backup_dir", "daily_hour"],
                &[],
            )?;
            identity(s, data)?;
            let current = read(s)?;
            let target = Path::new(protocol::text(&data["backup_dir"], 4096, true)?);
            let hour = data["daily_hour"]
                .as_u64()
                .filter(|h| *h < 24)
                .ok_or_else(|| Error::new(422, "DAILY_BACKUP_CONFIG_INVALID"))?;
            // Re-reading/retrying an already applied choice is harmless, including after a lost response.
            if current["backup_dir"] == data["backup_dir"]
                && current["daily_hour"] == data["daily_hour"]
            {
                return Ok(current);
            }
            if current["revision"] != data["expected_revision"] {
                return fail(409, "HOST_BACKUP_SETTINGS_CHANGED");
            }
            // A time-only change does not require a disconnected backup share to be online.
            let store_id = if current["backup_dir"] == data["backup_dir"] {
                s.config["backup_store_id"].clone()
            } else {
                directories::validate(s, target)?;
                let old_path = Path::new(s.config["backup_dir"].as_str().unwrap());
                let same = old_path
                    .canonicalize()
                    .ok()
                    .zip(target.canonicalize().ok())
                    .is_some_and(|(a, b)| a == b);
                let destination = if same {
                    backup::configured_destination(
                        target,
                        s.config["backup_store_id"].as_str().unwrap(),
                    )?
                } else {
                    backup::destination(target)?
                };
                destination["store_id"].clone()
            };
            let mut candidate = s.config.clone();
            candidate["backup_dir"] = json!(target);
            candidate["backup_store_id"] = store_id;
            candidate["daily_backup_hour"] = json!(hour);
            // One atomic file replacement publishes both the destination and time together.
            Auth::audit(
                &s.auth.connection()?,
                &actor,
                "host_backup_settings_requested",
                &serde_json::to_string(
                    &json!({"before":current,"after":{"backup_dir":target,"daily_hour":hour}}),
                )?,
            )?;
            files::replace_json(&s.root.join("private/service.json"), &candidate)?;
            s.config = candidate;
            read(s)
        }
        _ => fail(404, "NOT_FOUND"),
    }
}
fn identity(s: &Service, data: &Value) -> Result<()> {
    if data["ledger_id"].as_str().is_none() || data["ledger_id"] != s.config["ledger_id"] {
        return fail(409, "HOST_BACKUP_LEDGER_CHANGED");
    }
    Ok(())
}
