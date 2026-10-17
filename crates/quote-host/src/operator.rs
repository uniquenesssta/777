//! Local, authenticated maintenance operations; never exposed as arbitrary client paths.
use crate::{auth::Auth, backup, fail, files, service::Service, Result};
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
        if target.exists() {
            files::dir(target)?;
            // Windows may describe one directory by either its 8.3 alias or
            // its long name. Saving the daily policy must not treat that as
            // selecting a different, nonempty backup destination.
            let current = Path::new(s.config["backup_dir"].as_str().unwrap());
            if current.exists() && target.canonicalize()? == current.canonicalize()? {
                files::writable_directory(target)?;
                return backup::status(&s);
            }
        }
        let candidate = if target.exists() {
            target.canonicalize()?
        } else {
            let parent = target
                .parent()
                .ok_or_else(|| crate::Error::new(422, "BACKUP_PATH_INVALID"))?;
            files::dir(parent)?;
            parent.canonicalize()?.join(target.file_name().unwrap())
        };
        let daily = crate::daily_backup::config(&s)?;
        let hidden = daily["hidden_dir"].as_str().unwrap();
        if !hidden.is_empty() {
            let h = Path::new(hidden).canonicalize()?;
            if candidate == h {
                return fail(422, "BACKUP_DIRECTORY_CONFLICT");
            }
        }
        let destination = backup::destination(target)?;
        s.config["backup_dir"] = json!(target.to_string_lossy());
        s.config["backup_store_id"] = destination["store_id"].clone();
        files::replace_json(&root.join("private/service.json"), &s.config)?;
        // Saving a location must not consume today's snapshot before later business writes.
        backup::status(&s)
    })();
    let _ = s.auth.logout(token);
    result
}

pub fn configure_daily(
    root: &Path,
    target: &Path,
    hidden: &Path,
    hour: u8,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    // Authenticate before touching either destination. All setters are local operator commands.
    authorize(root, user, password, auxiliary)?;
    let previous = files::read_json(&root.join("private/service.json"))?;
    let daily_path = root.join("private/daily-backup.json");
    let old_daily = if daily_path.exists() {
        Some(files::read_json(&daily_path)?)
    } else {
        None
    };
    let result = (|| {
        if target == hidden {
            return fail(422, "BACKUP_DIRECTORY_CONFLICT");
        }
        if hour > 23 {
            return fail(422, "DAILY_BACKUP_CONFIG_INVALID");
        }
        // Validate the hidden destination against the candidate ordinary path before publishing either.
        let _owner = files::Owner::acquire(root)?;
        let mut candidate = Service::load(root, auxiliary, true)?;
        if !target.exists() {
            files::new_dir(target)?;
        }
        candidate.config["backup_dir"] = json!(target.to_string_lossy());
        crate::daily_backup::configure(&candidate, hidden, hour)?;
        drop(_owner);
        configure_backup(root, target, user, password, auxiliary)?;
        Ok(json!({"configured":true}))
    })();
    if result.is_err() {
        files::replace_json(&root.join("private/service.json"), &previous)?;
        if let Some(v) = old_daily {
            files::replace_json(&daily_path, &v)?;
        } else if daily_path.exists() {
            std::fs::remove_file(daily_path)?;
        }
    }
    result
}
