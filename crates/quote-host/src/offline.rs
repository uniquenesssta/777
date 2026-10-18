//! Read an offline directory through a disposable copy, without opening source SQLite files.
use crate::{
    auth::Auth, fail, files, outputs::Outputs, query::Queries, recovery, service::Service, Error,
    Result,
};
use quote_ledger::{integrity, store};
use serde_json::{json, Value};
use std::{
    fs::{self, File, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
};
struct Scratch(PathBuf);
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn source_file(path: &Path) -> Result<File> {
    files::local(path, true)?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // Keep the source immutable while copying, including when an older host starts.
        options.share_mode(1); // FILE_SHARE_READ; deny write/delete.
    }
    options.open(path).map_err(|e| {
        if cfg!(windows) && matches!(e.raw_os_error(), Some(32) | Some(33)) {
            Error::new(409, "SERVICE_OWNER_BUSY")
        } else {
            e.into()
        }
    })
}
pub fn export(
    root: &Path,
    package: &Path,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    files::dir(root)?;
    files::local(package, false)?;
    let root = fs::canonicalize(root)?;
    let parent = fs::canonicalize(
        package
            .parent()
            .ok_or_else(|| Error::new(422, "FILESYSTEM_PATH_REQUIRED"))?,
    )?;
    if parent.starts_with(&root) {
        return fail(422, "OFFLINE_TARGET_INSIDE_SOURCE");
    }
    if package.exists() {
        return fail(409, "PATH_ALREADY_EXISTS");
    }
    // Never create or rewrite an ownership marker in the source.
    let marker = root.join(".service-owner.777.lock");
    if !marker.exists() {
        return fail(409, "OFFLINE_OWNERSHIP_UNCONFIRMED");
    }
    let owner = source_file(&marker)?;
    fs2::FileExt::try_lock_exclusive(&owner).map_err(|_| Error::new(409, "SERVICE_OWNER_BUSY"))?;
    let mut config_file = source_file(&root.join("private/service.json"))?;
    let mut config_raw = Vec::new();
    (&mut config_file)
        .take(65537)
        .read_to_end(&mut config_raw)?;
    if config_raw.len() > 65536 {
        return fail(422, "HOST_CONFIG_INVALID");
    }
    let config: Value = serde_json::from_slice(&config_raw)?;
    if config["schema"] != "777-host-v1" {
        return fail(422, "HOST_CONFIG_INVALID");
    }
    let ledger_id = config["ledger_id"]
        .as_str()
        .ok_or_else(|| Error::new(422, "HOST_CONFIG_INVALID"))?;
    store::id(ledger_id)?;
    let data = crate::cluster::replica::data_directory(&root)?;
    let mut names = Vec::new();
    for name in ["ledger.sqlite3", "auth.sqlite3", "outputs.sqlite3"] {
        if name != "outputs.sqlite3" || data.join(name).exists() {
            names.push(name.to_owned());
            for suffix in ["-wal", "-journal"] {
                let n = format!("{name}{suffix}");
                if data.join(&n).exists() {
                    names.push(n);
                }
            }
        }
    }
    if data.join("output-blobs").exists() {
        files::dir(&data.join("output-blobs"))?;
        for entry in fs::read_dir(data.join("output-blobs"))? {
            let entry = entry?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| Error::new(422, "DATA_BACKUP_INVALID"))?;
            names.push(format!("output-blobs/{name}"));
            if names.len() > 100000 {
                return fail(413, "DATA_BACKUP_TOO_LARGE");
            }
        }
    }
    // Acquire every read handle before copying any bytes. Windows denies concurrent writers.
    let mut sources = Vec::new();
    let mut total = 0u64;
    for name in names {
        let file = source_file(&data.join(&name))?;
        total = total.saturating_add(file.metadata()?.len());
        if total > 512 * 1024 * 1024 {
            return fail(413, "DATA_BACKUP_TOO_LARGE");
        }
        sources.push((name, file));
    }
    let scratch = parent.join(format!(".777-offline-{}", store::uid()?));
    files::new_dir(&scratch)?;
    let cleanup = Scratch(scratch.clone());
    files::protect(&scratch, auxiliary)?;
    let private = scratch.join("private");
    files::new_dir(&private)?;
    files::new_dir(&private.join("output-blobs"))?;
    for (name, file) in &mut sources {
        let mut raw = Vec::new();
        file.take((512 * 1024 * 1024) + 1).read_to_end(&mut raw)?;
        if raw.len() > 512 * 1024 * 1024 {
            return fail(413, "DATA_BACKUP_TOO_LARGE");
        }
        files::new_file(&private.join(name), &raw)?;
    }
    let ledger = private.join("ledger.sqlite3");
    if integrity::inventory(&store::open(&ledger, false)?)?["ledger_id"] != ledger_id {
        return fail(409, "HOST_STORE_IDENTITY_CONFLICT");
    }
    let mut auth = Auth::open(private.join("auth.sqlite3"))?;
    let login = auth.login(&json!(user), &json!(password), "offline-working-copy")?;
    Auth::admin(
        &auth.authenticate(
            login["token"]
                .as_str()
                .ok_or_else(|| Error::new(401, "UNAUTHENTICATED"))?,
        )?,
    )?;
    let outputs = if private.join("outputs.sqlite3").exists() {
        Some(Outputs::open(private.join("outputs.sqlite3"), ledger_id)?)
    } else {
        None
    };
    let service = Service {
        root: scratch,
        config: config.clone(),
        ledger,
        auth,
        devices: None,
        outputs,
        queries: Queries::new()?,
        auxiliary,
        font: None,
        test_fault: None,
    };
    let data = recovery::capture(&service, &store::now()[..10])?;
    let raw = recovery::encode(&data)?;
    recovery::decode(&raw)?;
    files::new_file(package, &raw)?;
    drop(service);
    drop(cleanup);
    Ok(
        json!({"status":"offline_snapshot_created","ledger_id":config["ledger_id"],"source_unchanged":true}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (PathBuf, PathBuf) {
        let base = std::env::temp_dir().join(format!("777-offline-test-{}", store::uid().unwrap()));
        let root = base.join("源 业务目录");
        let private = root.join("private");
        fs::create_dir_all(&private).unwrap();
        let meta = store::create(&private.join("ledger.sqlite3")).unwrap();
        Auth::create(&private.join("auth.sqlite3"), "manager", "test-secret-123").unwrap();
        Outputs::create(
            &private.join("outputs.sqlite3"),
            meta["ledger_id"].as_str().unwrap(),
        )
        .unwrap();
        files::new_file(
            &private.join("service.json"),
            &serde_json::to_vec(&json!({"schema":"777-host-v1","ledger_id":meta["ledger_id"]}))
                .unwrap(),
        )
        .unwrap();
        drop(files::Owner::acquire(&root).unwrap());
        (base, root)
    }
    fn digest_tree(root: &Path) -> std::collections::BTreeMap<PathBuf, String> {
        let mut map = std::collections::BTreeMap::new();
        for entry in fs::read_dir(root).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                map.extend(digest_tree(&path));
            } else {
                map.insert(path.clone(), store::hash(fs::read(path).unwrap()));
            }
        }
        map
    }
    #[test]
    fn offline_copy_preserves_source_and_enforces_authority_and_ownership() {
        let (base, root) = fixture();
        let package = base.join("read.qbackup");
        let before = digest_tree(&root);
        let owner = files::Owner::acquire(&root).unwrap();
        assert_eq!(
            export(
                &root,
                &package,
                "manager",
                "test-secret-123",
                !cfg!(windows)
            )
            .unwrap_err()
            .code,
            "SERVICE_OWNER_BUSY"
        );
        drop(owner);
        assert!(export(&root, &package, "manager", "wrong", !cfg!(windows)).is_err());
        assert!(!package.exists());
        assert_eq!(digest_tree(&root), before);
        let result = export(
            &root,
            &package,
            "manager",
            "test-secret-123",
            !cfg!(windows),
        )
        .unwrap();
        let data = recovery::decode(&fs::read(&package).unwrap()).unwrap();
        assert_eq!(data.inventory["ledger_id"], result["ledger_id"]);
        assert_eq!(digest_tree(&root), before);
        assert!(!String::from_utf8(fs::read(&package).unwrap())
            .unwrap()
            .contains("test-secret-123"));
        assert!(!fs::read_dir(&base).unwrap().any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".777-offline-")));
        fs::remove_dir_all(base).unwrap();
    }
    #[test]
    fn source_without_ownership_marker_is_not_modified_to_make_it_readable() {
        let (base, root) = fixture();
        fs::remove_file(root.join(".service-owner.777.lock")).unwrap();
        let before = digest_tree(&root);
        assert_eq!(
            export(
                &root,
                &base.join("x.qbackup"),
                "manager",
                "test-secret-123",
                !cfg!(windows)
            )
            .unwrap_err()
            .code,
            "OFFLINE_OWNERSHIP_UNCONFIRMED"
        );
        assert_eq!(digest_tree(&root), before);
        fs::remove_dir_all(base).unwrap();
    }
}
