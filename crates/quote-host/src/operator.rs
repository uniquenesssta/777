//! Local, authenticated maintenance operations; never exposed as arbitrary client paths.
use crate::{auth::Auth, backup, fail, files, service::Service, Result};
use quote_ledger::store::uid;
use serde_json::{json, Value};
use std::path::Path;

pub fn authorize(root: &Path, user: &str, password: &str, auxiliary: bool) -> Result<Value> {
    let _owner = files::Owner::acquire(root)?;
    let mut s = Service::load(root, auxiliary, true)?;
    let login = s
        .auth
        .login(&json!(user), &json!(password), "developer-operator")?;
    let token = login["token"].as_str().unwrap();
    let result = (|| {
        Auth::admin(&s.auth.authenticate(token)?)?;
        Ok(json!({"ledger_id":s.config["ledger_id"],"backup_dir":s.config["backup_dir"]}))
    })();
    let _ = s.auth.logout(token);
    result
}

pub fn configure_backup(
    root: &Path,
    target: &Path,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    let _owner = files::Owner::acquire(root)?;
    let mut s = Service::load(root, auxiliary, true)?;
    let login = s
        .auth
        .login(&json!(user), &json!(password), "developer-backup-location")?;
    let token = login["token"].as_str().unwrap();
    let result = (|| {
        Auth::admin(&s.auth.authenticate(token)?)?;
        if target == Path::new(s.config["backup_dir"].as_str().unwrap()) {
            return backup::status(&s);
        }
        if target.exists() {
            files::dir(target)?;
        } else {
            files::local(&target.with_file_name(".777-parent-check"), false)?;
        }
        let parent = target
            .parent()
            .ok_or_else(|| crate::Error::new(422, "BACKUP_PATH_INVALID"))?;
        files::dir(parent)?;
        let canonical_root = root.canonicalize()?;
        let candidate = parent.canonicalize()?.join(target.file_name().unwrap());
        if candidate.starts_with(&canonical_root) || canonical_root.starts_with(&candidate) {
            return fail(422, "BACKUP_DIRECTORY_CONFLICT");
        }
        if target.exists() {
            files::dir(target)?;
            if std::fs::read_dir(target)?.next().is_some() {
                return fail(409, "BACKUP_REQUIRES_EMPTY_DIRECTORY");
            }
        } else {
            files::new_dir(target)?;
        }
        let security = files::protect(target, auxiliary)?;
        let store = uid()?;
        files::new_file(
            &target.join("777-backups.json"),
            &serde_json::to_vec(&json!({
                "format":"777-backups-v1","store_id":store,"security":security,
                "backups":[],"last_success":null,"last_error":null
            }))?,
        )?;
        let previous = s.config.clone();
        s.config["backup_dir"] = json!(target.to_string_lossy());
        s.config["backup_store_id"] = json!(store);
        let config_file = root.join("private/service.json");
        files::replace_json(&config_file, &s.config)?;
        // The existing full backup path performs independent restore verification.
        match backup::create(&s, "maintenance") {
            Ok(value) => Ok(value),
            Err(error) => {
                files::replace_json(&config_file, &previous)?;
                Err(error)
            }
        }
    })();
    let _ = s.auth.logout(token);
    result
}
