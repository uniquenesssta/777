use crate::{
    auth::{self, Auth},
    fail, files, host,
    outputs::Outputs,
    protocol,
    service::Service,
    Error, Result,
};
use quote_ledger::{
    integrity,
    store::{self, id},
};
use rusqlite::params;
use serde_json::{json, Value};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};
const BASE: [&str; 5] = [
    "ledger.sqlite3",
    "auth.sqlite3",
    "tls-key.pem",
    "tls-cert.pem",
    "service.json",
];
const WORKER: [&str; 2] = ["rust-ledger-worker.exe", "rust-notices.txt"];
const HOST: [&str; 2] = ["rust-service-host.exe", "rust-host-notices.txt"];
fn manager(s: &Service) -> Result<(PathBuf, Value)> {
    let p = PathBuf::from(
        s.config["backup_dir"]
            .as_str()
            .ok_or_else(|| Error::new(422, "BACKUP_PATH_INVALID"))?,
    );
    files::dir(&p)?;
    let v = files::read_json(&p.join("777-backups.json"))?;
    if v["format"] != "777-backups-v1"
        || v["store_id"] != s.config["backup_store_id"]
        || !v["backups"].is_array()
    {
        return fail(503, "BACKUP_STORE_IDENTITY_CONFLICT");
    }
    Ok((p, v))
}
/// Adopt a usable backup directory without replacing unrelated files or permissions.
pub(crate) fn destination(path: &Path) -> Result<Value> {
    if !path.exists() {
        files::new_dir(path)?;
    }
    let security = files::writable_directory(path)?;
    let marker = path.join("777-backups.json");
    if marker.exists() {
        let value = files::read_json(&marker)?;
        if value["format"] != "777-backups-v1"
            || !value["backups"].is_array()
            || value["store_id"].as_str().is_none_or(|s| id(s).is_err())
        {
            return fail(409, "BACKUP_STORE_IDENTITY_CONFLICT");
        }
        return Ok(value);
    }
    let value = json!({"format":"777-backups-v1","store_id":store::uid()?,
        "security":security,"backups":[],"last_success":null,"last_error":null});
    files::new_file(&marker, &serde_json::to_vec(&value)?)?;
    Ok(value)
}

pub fn status(s: &Service) -> Result<Value> {
    Ok(manager(s)?.1)
}
pub(crate) fn accounts(ledger: &Path, auth: &Auth) -> Result<()> {
    let c = store::open(ledger, false)?;
    let mut st=c.prepare("SELECT owner_id FROM orders UNION SELECT author_id FROM notes UNION SELECT actor_id FROM requests UNION SELECT published_by FROM price_versions")?;
    let owners = st
        .query_map([], |r| r.get::<_, String>(0))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let c = auth.connection()?;
    for owner in owners {
        let exists: bool = c.query_row(
            "SELECT EXISTS(SELECT 1 FROM users WHERE id=?)",
            [owner],
            |r| r.get(0),
        )?;
        if !exists {
            return fail(503, "BACKUP_ACCOUNT_MAPPING_INCOMPLETE");
        }
    }
    Ok(())
}
pub fn manifest(folder: &Path) -> Result<Value> {
    files::dir(folder)?;
    let v = files::read_json(&folder.join("manifest.json"))?;
    protocol::fields(
        &v,
        &["format", "backup_id", "ledger_id", "files", "inventory"],
        &[],
    )?;
    id(protocol::text(&v["backup_id"], 36, true)?)?;
    let format = v["format"].as_str().unwrap_or("");
    if ![
        "777-service-bundle-v1",
        "777-service-bundle-v2",
        "777-service-bundle-v3",
        "777-service-bundle-v4",
        "777-service-bundle-v5",
    ]
    .contains(&format)
    {
        return fail(422, "SERVICE_BACKUP_FORMAT_INVALID");
    }
    let names = v["files"]
        .as_object()
        .ok_or_else(|| Error::new(422, "SERVICE_BACKUP_FORMAT_INVALID"))?;
    let mut basics = BASE
        .into_iter()
        .map(str::to_string)
        .collect::<BTreeSet<_>>();
    if matches!(
        format,
        "777-service-bundle-v3" | "777-service-bundle-v4" | "777-service-bundle-v5"
    ) {
        basics.extend(WORKER.map(str::to_string));
    }
    if matches!(format, "777-service-bundle-v4" | "777-service-bundle-v5") {
        basics.extend(HOST.map(str::to_string));
    }
    if format == "777-service-bundle-v5" {
        basics.insert("devices.sqlite3".into());
    }
    let output = names.contains_key("outputs.sqlite3");
    if output {
        basics.insert("outputs.sqlite3".into());
    }
    if format == "777-service-bundle-v2" && !output
        || format == "777-service-bundle-v1" && names.len() != 5
    {
        return fail(422, "SERVICE_BACKUP_FORMAT_INVALID");
    }
    let mut blobs = BTreeSet::new();
    for name in names.keys() {
        if basics.contains(name) {
            continue;
        }
        if let Some(n) = name.strip_prefix("output-blobs/") {
            let (key, ext) = n
                .rsplit_once('.')
                .ok_or_else(|| Error::new(422, "SERVICE_BACKUP_FORMAT_INVALID"))?;
            id(key)?;
            if !output || !["png", "xlsx"].contains(&ext) {
                return fail(422, "SERVICE_BACKUP_FORMAT_INVALID");
            }
            blobs.insert(n.to_string());
        } else {
            return fail(422, "SERVICE_BACKUP_FORMAT_INVALID");
        }
    }
    if basics.iter().any(|n| !names.contains_key(n)) {
        return fail(422, "SERVICE_BACKUP_FORMAT_INVALID");
    }
    let mut roots = basics.clone();
    roots.insert("manifest.json".into());
    if output {
        roots.insert("output-blobs".into());
        files::dir(&folder.join("output-blobs"))?;
        let actual = fs::read_dir(folder.join("output-blobs"))?
            .map(|e| e.map(|e| e.file_name().to_string_lossy().to_string()))
            .collect::<std::io::Result<BTreeSet<_>>>()?;
        if actual != blobs {
            return fail(422, "SERVICE_BACKUP_FILES_INVALID");
        }
    }
    let actual = fs::read_dir(folder)?
        .map(|e| e.map(|e| e.file_name().to_string_lossy().to_string()))
        .collect::<std::io::Result<BTreeSet<_>>>()?;
    if actual != roots {
        return fail(422, "SERVICE_BACKUP_FILES_INVALID");
    }
    for (name, sha) in names {
        if files::sha(&folder.join(name))? != *sha {
            return fail(422, "SERVICE_BACKUP_HASH_INVALID");
        }
    }
    let config = files::read_json(&folder.join("service.json"))?;
    host::validate_resources(folder, &config)?;
    if (format == "777-service-bundle-v5")
        != (config.get("device_auth") == Some(&json!(crate::devices::FORMAT)))
    {
        return fail(422, "DEVICE_BACKUP_INVALID");
    }
    if format == "777-service-bundle-v5" {
        crate::devices::Devices::open(folder.join("devices.sqlite3"))?;
    }

    if matches!(
        format,
        "777-service-bundle-v3" | "777-service-bundle-v4" | "777-service-bundle-v5"
    ) && config.get("rust_worker_sha256").is_none()
    {
        return fail(422, "SERVICE_BACKUP_WORKER_INVALID");
    }
    if matches!(format, "777-service-bundle-v4" | "777-service-bundle-v5")
        && config.get("rust_host_sha256").is_none()
    {
        return fail(422, "SERVICE_BACKUP_HOST_INVALID");
    }
    if matches!(format, "777-service-bundle-v1" | "777-service-bundle-v2")
        && (config.get("rust_worker_sha256").is_some()
            || config.get("ledger_backend").is_some_and(|v| v != "python"))
    {
        return fail(422, "SERVICE_BACKUP_BACKEND_INVALID");
    }
    let inv = integrity::inventory(&store::open(&folder.join("ledger.sqlite3"), false)?)?;
    if inv != v["inventory"]
        || inv["ledger_id"] != v["ledger_id"]
        || config["ledger_id"] != v["ledger_id"]
    {
        return fail(422, "SERVICE_BACKUP_INVENTORY_INVALID");
    }
    if host::certificate_sha(&folder.join("tls-cert.pem"))? != config["certificate_sha256"] {
        return fail(422, "CERTIFICATE_IDENTITY_CONFLICT");
    }
    let auth = Auth::open(folder.join("auth.sqlite3"))?;
    accounts(&folder.join("ledger.sqlite3"), &auth)?;
    if format == "777-service-bundle-v5" {
        crate::devices::Devices::open(folder.join("devices.sqlite3"))?.validate_accounts(&auth)?;
    }
    if output {
        let outputs = Outputs::open(
            folder.join("outputs.sqlite3"),
            v["ledger_id"].as_str().unwrap(),
        )?;
        let expected = outputs
            .validate_ledger(&folder.join("ledger.sqlite3"))?
            .into_iter()
            .collect::<BTreeSet<_>>();
        let actual = names
            .keys()
            .filter(|n| n.starts_with("output-blobs/"))
            .cloned()
            .collect();
        if expected != actual {
            return fail(422, "SERVICE_BACKUP_OUTPUT_INDEX_INVALID");
        }
    }
    Ok(v)
}
pub fn restore(
    folder: &Path,
    target: &Path,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    let value = manifest(folder)?;
    let user = auth::username(&json!(user))?;
    auth::password(&json!(password))?;
    if target.exists() {
        return fail(409, "RESTORE_REQUIRES_NEW_DIRECTORY");
    }
    let original = Auth::open(folder.join("auth.sqlite3"))?;
    let c = original.connection()?;
    let admin: String = c
        .query_row(
            "SELECT id FROM users WHERE username=? AND role='admin'",
            [user],
            |r| r.get(0),
        )
        .map_err(|_| Error::new(422, "RESTORE_ADMIN_NOT_FOUND"))?;
    drop(c);
    files::new_dir(target)?;
    let private = target.join("private");
    files::new_dir(&private)?;
    let security = files::protect(&private, auxiliary)?;
    let result = (|| -> Result<Value> {
        if value["files"]
            .as_object()
            .unwrap()
            .keys()
            .any(|n| n.starts_with("output-blobs/"))
            || value["files"].get("outputs.sqlite3").is_some()
        {
            files::new_dir(&private.join("output-blobs"))?;
        }
        for name in value["files"].as_object().unwrap().keys() {
            files::copy(&folder.join(name), &private.join(name))?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            for name in ["rust-ledger-worker.exe", "rust-service-host.exe"] {
                let p = private.join(name);
                if p.exists() {
                    fs::set_permissions(p, fs::Permissions::from_mode(0o700))?;
                }
            }
        }
        let auth = Auth::open(private.join("auth.sqlite3"))?;
        let c = auth.connection()?;
        let mut st = c.prepare("SELECT id FROM users")?;
        let ids = st
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        drop(st);
        let tx = c.unchecked_transaction()?;
        tx.execute("DELETE FROM sessions", [])?;
        for id in ids {
            let salt = auth::random::<16>()?;
            let hashed = if id == admin {
                auth::verifier(password, &salt)?
            } else {
                auth::random::<32>()?.to_vec()
            };
            tx.execute(
                "UPDATE users SET enabled=?,salt=?,verifier=?,epoch=epoch+1 WHERE id=?",
                params![i64::from(id == admin), salt.as_slice(), hashed, id],
            )?;
        }
        tx.commit()?;
        drop(c);
        if private.join("devices.sqlite3").exists() {
            crate::devices::Devices::open(private.join("devices.sqlite3"))?.revoke_all()?;
        }
        let mut config = files::read_json(&private.join("service.json"))?;
        config["private_security"] = security;
        config["maintenance"] = json!(true);
        files::replace_json(&private.join("service.json"), &config)?;
        files::copy(
            &private.join("tls-cert.pem"),
            &target.join("service-cert.pem"),
        )?;
        let inv = integrity::inventory(&store::open(&private.join("ledger.sqlite3"), false)?)?;
        if inv != value["inventory"] {
            return fail(503, "RESTORED_LEDGER_MISMATCH");
        }
        accounts(&private.join("ledger.sqlite3"), &auth)?;
        if let Some(o) = value["files"].get("outputs.sqlite3") {
            let _ = o;
            Outputs::open(
                private.join("outputs.sqlite3"),
                inv["ledger_id"].as_str().unwrap(),
            )?
            .validate_ledger(&private.join("ledger.sqlite3"))?;
        }
        Ok(
            json!({"inventory":inv,"maintenance":true,"sessions_revoked":true,"certificate_sha256":config["certificate_sha256"],"host_backend":config.get("service_backend").unwrap_or(&json!("python"))}),
        )
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(target);
    }
    result
}
pub fn create(s: &Service, kind: &str) -> Result<Value> {
    if !["rolling", "daily", "maintenance"].contains(&kind) {
        return fail(422, "INVALID_BACKUP_KIND");
    }
    crate::daily_backup::create(s)
}
pub fn due(s: &Service) -> Result<Option<Value>> {
    crate::daily_backup::due(s)
}
pub fn retain(s: &Service, rolling: usize, daily: usize) -> Result<()> {
    let (root, _) = manager(s)?;
    let index = root.join("777-backups.json");
    let _lock = files::Lock::acquire(&index)?;
    let service_index = root.join("777-service-backups.json");
    let _service_lock = files::Lock::acquire(&service_index)?;
    let mut data = files::read_json(&index)?;
    let mut bundles = files::read_json(&service_index)?;
    let entries = data["backups"]
        .as_array()
        .ok_or_else(|| Error::new(503, "BACKUP_INDEX_INVALID"))?;
    let mut keep = BTreeSet::new();
    for (kind, count) in [("rolling", rolling), ("daily", daily)] {
        for e in entries
            .iter()
            .rev()
            .filter(|v| v["kind"] == kind)
            .take(count)
        {
            keep.insert(e["backup_id"].as_str().unwrap().to_string());
        }
    }
    for e in entries.iter().filter(|e| e["kind"] == "maintenance") {
        keep.insert(e["backup_id"].as_str().unwrap().to_string());
    }
    if let Some(k) = data["last_success"]["backup_id"].as_str() {
        keep.insert(k.into());
    }
    let mut delete = vec![];
    for e in entries {
        let k = protocol::text(&e["backup_id"], 36, true)?;
        id(k)?;
        if keep.contains(k) {
            continue;
        }
        let folder = root.join(k);
        files::dir(&folder)?;
        let m = files::read_json(&folder.join("manifest.json"))?;
        let actual = fs::read_dir(&folder)?
            .map(|e| e.map(|e| e.file_name().to_string_lossy().to_string()))
            .collect::<std::io::Result<BTreeSet<_>>>()?;
        if m["backup_id"] != k
            || files::sha(&folder.join("ledger.sqlite3"))? != e["sha256"]
            || actual
                != ["ledger.sqlite3".to_string(), "manifest.json".to_string()]
                    .into_iter()
                    .collect()
        {
            return fail(503, "BACKUP_RETENTION_REFUSED");
        }
        let b = root.join("service-bundles").join(k);
        if b.exists() {
            manifest(&b)?;
            delete.push(b);
        }
        delete.push(folder);
    }
    data["backups"]
        .as_array_mut()
        .unwrap()
        .retain(|e| keep.contains(e["backup_id"].as_str().unwrap_or("")));
    bundles["entries"]
        .as_array_mut()
        .ok_or_else(|| Error::new(503, "SERVICE_BACKUP_INDEX_INVALID"))?
        .retain(|e| keep.contains(e["backup_id"].as_str().unwrap_or("")));
    files::replace_json(&index, &data)?;
    files::replace_json(&service_index, &bundles)?;
    for p in delete {
        fs::remove_dir_all(p)?;
    }
    Ok(())
}
