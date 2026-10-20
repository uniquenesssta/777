//! Daily immutable pairs with separately tracked delivery to two configured locations.
mod presentation;
mod schedule;
use crate::{fail, files, recovery, service::Service, Error, Result};
pub use presentation::public_status;
use quote_ledger::store;
pub use schedule::{check, due, CHECK_INTERVAL};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};
pub fn config(s: &Service) -> Result<Value> {
    let p = s.root.join("private/daily-backup.json");
    let mut v = if p.exists() {
        files::read_json(&p)?
    } else {
        json!({"format":"777-daily-config-v1","hidden_dir":"","daily_hour":23})
    };
    if let Some(hour) = s.config.get("daily_backup_hour") {
        v["daily_hour"] = hour.clone();
    }
    if v["format"] != "777-daily-config-v1"
        || !v["hidden_dir"].is_string()
        || !v["daily_hour"].as_u64().is_some_and(|h| h < 24)
    {
        return fail(422, "DAILY_BACKUP_CONFIG_INVALID");
    }
    Ok(v)
}
fn business_day(now: time::OffsetDateTime) -> String {
    now.to_offset(time::UtcOffset::from_hms(8, 0, 0).unwrap())
        .date()
        .to_string()
}
fn cache_root(s: &Service) -> PathBuf {
    s.root.join("private/daily-cache")
}
fn index_path(s: &Service) -> PathBuf {
    s.root.join("private/daily-backups.json")
}
pub fn status(s: &Service) -> Result<Value> {
    let p = index_path(s);
    if p.exists() {
        files::read_json(&p)
    } else {
        Ok(json!({"format":"777-daily-state-v1","entries":{}}))
    }
}
fn public_entry(e: &Value) -> Value {
    json!({"backup_id":e["snapshot_id"],"kind":"daily","created_at":e["created_at"],"business_date":e["date"],"verified_restore":true,"verification":"logical-ledger-inventory","delivery_complete":presentation::complete(e),"format":e.get("data_format").cloned().unwrap_or_else(||json!(recovery::LEGACY_FORMAT))})
}
fn ensure_destination(_s: &Service, p: &Path) -> Result<()> {
    files::dir(p)
}
fn deliver(s: &Service, target: &Path, date: &str, snapshot: &str, cache: &Path) -> Result<()> {
    ensure_destination(s, target)?;
    let folder = target.join(format!(
        "{}-{date}-{snapshot}",
        s.config["ledger_id"].as_str().unwrap()
    ));
    if folder.exists() {
        files::dir(&folder)?;
        for name in ["data.qbackup", "data.xlsx"] {
            if files::sha(&folder.join(name))? != files::sha(&cache.join(name))? {
                return fail(409, "DAILY_BACKUP_FILE_CONFLICT");
            }
        }
        return Ok(());
    }
    let partial = target.join(format!(".daily-{}.partial", store::uid()?));
    files::new_dir(&partial)?;
    let result = (|| {
        for name in ["data.qbackup", "data.xlsx"] {
            files::copy(&cache.join(name), &partial.join(name))?;
            if files::sha(&partial.join(name))? != files::sha(&cache.join(name))? {
                return fail(503, "DATA_BACKUP_HASH_INVALID");
            }
        }
        quote_diagnostics::io_result("backup.publish", &folder, fs::rename(&partial, &folder))?;
        Ok(())
    })();
    if partial.exists() {
        let _ = fs::remove_dir_all(partial);
    }
    result
}
pub fn create(s: &Service) -> Result<Value> {
    let current = business_day(time::OffsetDateTime::now_utc());
    create_date(s, &current, &current, false)
}
fn create_date(s: &Service, date: &str, current: &str, pending_only: bool) -> Result<Value> {
    let cfg = config(s)?;
    let index = index_path(s);
    let _lock = files::Lock::acquire(&index)?;
    let mut state = status(s)?;
    let root = cache_root(s);
    if !root.exists() {
        files::new_dir(&root)?;
    }
    let cache = root.join(date);
    if !cache.exists() {
        if date != current {
            return fail(503, "DAILY_SNAPSHOT_MISSING");
        }
        let tmp = root.join(format!(".{}.partial", store::uid()?));
        files::new_dir(&tmp)?;
        quote_diagnostics::event("backup.snapshot.start", json!({"date":date}));
        let generated: Result<()> = (|| {
            let data = recovery::capture_live(s, date)?;
            let raw = recovery::encode(&data)?;
            let decoded = recovery::decode(&raw)?;
            recovery::restore_ledger(&decoded, &tmp.join("verify.sqlite3"))?;
            fs::remove_file(tmp.join("verify.sqlite3"))?;
            let excel = quote_excel::backup::write(&serde_json::to_value(&data)?)
                .map_err(|e| Error::new(422, &e.code))?;
            files::new_file(&tmp.join("data.qbackup"), &raw)?;
            files::new_file(&tmp.join("data.xlsx"), &excel)?;
            fs::rename(&tmp, &cache)?;
            Ok(())
        })();
        if tmp.exists() {
            let _ = fs::remove_dir_all(tmp);
        }
        quote_diagnostics::event(
            "backup.snapshot.finish",
            json!({"date":date,"error":generated.as_ref().err().map(|e|&e.code)}),
        );
        generated?;
    }
    let data = recovery::decode(&files::read(&cache.join("data.qbackup"), recovery::LIMIT)?)?;
    let mut e = json!({"data_format":data.format,"date":date,"snapshot_id":data.snapshot_id,"created_at":data.created_at,"normal":null,"hidden":null});
    let previous = &state["entries"][date];
    let mut normal_delivered = false;
    for (label, target) in [
        ("normal", s.config["backup_dir"].as_str().unwrap()),
        ("hidden", cfg["hidden_dir"].as_str().unwrap()),
    ] {
        if pending_only
            && previous["snapshot_id"] == e["snapshot_id"]
            && schedule::delivered(previous, label, &json!(target))
        {
            e[label] = previous[label].clone();
            continue;
        }
        quote_diagnostics::event(
            "backup.delivery.start",
            json!({"destination":label,"path":target,"date":date}),
        );
        let result = (|| {
            if target.is_empty() {
                return fail(422, "HIDDEN_BACKUP_NOT_CONFIGURED");
            }
            let marker = Path::new(target).join(if label == "normal" {
                "777-backups.json"
            } else {
                "777-hidden-data.json"
            });
            let identity = files::read_json(&marker)?;
            if (label == "normal"
                && (identity["format"] != "777-backups-v1"
                    || identity["store_id"] != s.config["backup_store_id"]))
                || (label == "hidden" && identity["format"] != "777-hidden-data-v1")
            {
                return fail(503, "BACKUP_STORE_IDENTITY_CONFLICT");
            }
            deliver(s, Path::new(target), date, &data.snapshot_id, &cache)
        })();
        quote_diagnostics::event(
            "backup.delivery.finish",
            json!({"destination":label,"path":target,"date":date,"error":result.as_ref().err().map(|e|&e.code)}),
        );
        if label == "normal" && result.is_ok() {
            normal_delivered = true;
        }
        e[label] = match result {
            Ok(()) => json!({"ok":true,"target":target}),
            Err(err) => json!({"ok":false,"target":target,"error":err.code}),
        };
    }
    state["entries"][date] = e.clone();
    files::replace_json(&index, &state)?;
    let entry = public_entry(&e);
    // Only the destination just written needs its index updated. A previously delivered
    // ordinary copy may be temporarily offline while the other copy catches up.
    if normal_delivered {
        let index = Path::new(s.config["backup_dir"].as_str().unwrap()).join("777-backups.json");
        let _lock = files::Lock::acquire(&index)?;
        let mut old = files::read_json(&index)?;
        if old["store_id"] != s.config["backup_store_id"] {
            return fail(503, "BACKUP_STORE_IDENTITY_CONFLICT");
        }
        if !old["backups"]
            .as_array()
            .is_some_and(|v| v.iter().any(|v| v["backup_id"] == entry["backup_id"]))
        {
            old["backups"]
                .as_array_mut()
                .ok_or_else(|| Error::new(503, "BACKUP_STORE_IDENTITY_CONFLICT"))?
                .push(entry.clone());
        }
        old["last_success"] = entry.clone();
        old["last_error"] = Value::Null;
        files::replace_json(&index, &old)?;
    }
    if e["normal"]["ok"] == true {
        s.auth.record_backup(Some(&entry), None)?;
    } else {
        s.auth.record_backup(None, Some("DAILY_BACKUP_FAILED"))?;
        return fail(503, "DAILY_BACKUP_FAILED");
    }
    Ok(entry)
}
pub fn configure(s: &Service, hidden: &Path, hour: u8) -> Result<Value> {
    quote_diagnostics::event(
        "backup.configure",
        json!({"hidden_path":hidden,"hour":hour}),
    );
    if hour > 23 {
        return fail(422, "DAILY_BACKUP_CONFIG_INVALID");
    }
    if !hidden.exists() {
        files::new_dir(hidden)?;
    }
    ensure_destination(s, hidden)?;
    let normal = Path::new(s.config["backup_dir"].as_str().unwrap()).canonicalize()?;
    let h = hidden.canonicalize()?;
    if h == normal {
        return fail(422, "BACKUP_DIRECTORY_CONFLICT");
    }
    let marker = hidden.join("777-hidden-data.json");
    if marker.exists() && files::read_json(&marker)?["format"] != "777-hidden-data-v1" {
        return fail(409, "BACKUP_STORE_IDENTITY_CONFLICT");
    }
    files::writable_directory(hidden)?;
    if !marker.exists() {
        files::new_file(
            &marker,
            &serde_json::to_vec(&json!({"format":"777-hidden-data-v1"}))?,
        )?;
    }
    let cfg = json!({"format":"777-daily-config-v1","hidden_dir":hidden.to_string_lossy(),"daily_hour":hour});
    files::replace_json(&s.root.join("private/daily-backup.json"), &cfg)?;
    Ok(cfg)
}

#[cfg(test)]
mod tests {
    use super::schedule::due_at;
    use super::*;
    use crate::{auth::Auth, query::Queries};
    #[test]
    fn beijing_rollover_restart_dedup_missed_days_and_unchanged_ledger() {
        let base = std::env::temp_dir().join(format!("777-daily-clock-{}", store::uid().unwrap()));
        struct Owned(PathBuf);
        impl Drop for Owned {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
        files::new_dir(&base).unwrap();
        let _owned = Owned(base.clone());
        let root = base.join("host");
        files::new_dir(&root).unwrap();
        files::new_dir(&root.join("private")).unwrap();
        let normal = base.join("normal");
        files::new_dir(&normal).unwrap();
        let ledger = root.join("private/ledger.sqlite3");
        let inv = store::create(&ledger).unwrap();
        let store_id = store::uid().unwrap();
        files::replace_json(&normal.join("777-backups.json"),&json!({"format":"777-backups-v1","store_id":store_id,"backups":[],"last_success":null})).unwrap();
        let s = Service {
            root: root.clone(),
            config: json!({"ledger_id":inv["ledger_id"],"backup_dir":normal,"backup_store_id":store_id}),
            ledger,
            auth: Auth::create(
                &root.join("private/auth.sqlite3"),
                "admin",
                "synthetic-password-123",
            )
            .unwrap(),
            devices: None,
            outputs: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: None,
        };
        let hidden = base.join("hidden");
        configure(&s, &hidden, 23).unwrap();
        let before = time::Date::from_calendar_date(2026, time::Month::October, 16)
            .unwrap()
            .with_hms(14, 59, 59)
            .unwrap()
            .assume_utc();
        assert!(due_at(&s, before).unwrap().is_none());
        let first = due_at(&s, before + time::Duration::seconds(1))
            .unwrap()
            .unwrap();
        assert_eq!(first["business_date"], "2026-10-16");
        assert!(due_at(&s, before + time::Duration::minutes(1))
            .unwrap()
            .is_none());
        // Every scheduling decision is reloaded from disk, as after a service restart.
        let after_midnight = before + time::Duration::minutes(61);
        assert_eq!(business_day(after_midnight), "2026-10-17");
        assert!(due_at(&s, after_midnight).unwrap().is_none());
        let second = due_at(
            &s,
            before + time::Duration::days(1) + time::Duration::seconds(1),
        )
        .unwrap()
        .unwrap();
        assert_ne!(first["backup_id"], second["backup_id"]);
        assert!(!cache_root(&s).join("2026-10-16").exists());
        let last = due_at(
            &s,
            before + time::Duration::days(4) + time::Duration::seconds(1),
        )
        .unwrap()
        .unwrap();
        assert_eq!(last["business_date"], "2026-10-20");
        assert_eq!(status(&s).unwrap()["entries"].as_object().unwrap().len(), 3);
        assert_eq!(
            fs::read_dir(&normal)
                .unwrap()
                .filter_map(|v| v.ok())
                .filter(|v| v.path().is_dir())
                .count(),
            3
        );
        assert_eq!(integrity_inventory(&s), inv);
    }
    fn integrity_inventory(s: &Service) -> Value {
        quote_ledger::integrity::inventory(&store::open(&s.ledger, false).unwrap()).unwrap()
    }
}
