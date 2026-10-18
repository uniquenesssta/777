use super::config::{self, Config};
use crate::{
    auth::Auth, backup, devices::Devices, fail, files, outputs::Outputs, service::Service, Error,
    Result,
};
use quote_ledger::{integrity, store};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
pub const FORMAT: &str = "777-cluster-snapshot-v1";
pub const FORMAT_V2: &str = "777-cluster-snapshot-v2";
pub const CHUNK: usize = 256 * 1024;
pub const MANIFEST_LIMIT: usize = 8 * 1024 * 1024;
const FILE_LIMIT: u64 = 256 * 1024 * 1024;
const TOTAL_LIMIT: u64 = 8 * 1024 * 1024 * 1024;
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FileEntry {
    pub size: u64,
    pub sha256: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub cluster_id: String,
    pub ledger_id: String,
    pub generation: u64,
    pub inventory: Value,
    pub files: BTreeMap<String, FileEntry>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Publication {
    pub generation: u64,
    pub sha256: String,
}
pub fn hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn valid_name(name: &str) -> bool {
    if [
        "ledger.sqlite3",
        "auth.sqlite3",
        "devices.sqlite3",
        "outputs.sqlite3",
    ]
    .contains(&name)
    {
        return true;
    }
    let Some(name) = name.strip_prefix("output-blobs/") else {
        return false;
    };
    let Some((id, extension)) = name.rsplit_once('.') else {
        return false;
    };
    store::id(id).is_ok() && ["xlsx", "png"].contains(&extension)
}
pub fn generations(root: &Path) -> PathBuf {
    config::directory(root).join("generations")
}
pub fn folder(root: &Path, p: &Publication) -> Result<PathBuf> {
    if p.generation == 0 || p.generation > i64::MAX as u64 || !hex(&p.sha256) {
        return fail(422, "CLUSTER_SNAPSHOT_INVALID");
    }
    Ok(generations(root).join(format!("{:020}_{}", p.generation, p.sha256)))
}
pub fn current(root: &Path) -> Result<Option<Publication>> {
    let path = config::directory(root).join("current.json");
    if !path.try_exists()? {
        return Ok(None);
    }
    let value: Publication = serde_json::from_slice(&files::read(&path, 16384)?)?;
    folder(root, &value)?;
    Ok(Some(value))
}
pub fn read(root: &Path, p: &Publication) -> Result<Manifest> {
    let raw = files::read(&folder(root, p)?.join("manifest.json"), MANIFEST_LIMIT)?;
    if store::hash(&raw) != p.sha256 {
        return fail(503, "CLUSTER_MANIFEST_HASH_INVALID");
    }
    let m: Manifest = serde_json::from_slice(&raw)?;
    validate_manifest(&m, &config::required(root)?)?;
    if m.generation != p.generation {
        return fail(409, "CLUSTER_GENERATION_CONFLICT");
    }
    Ok(m)
}
pub fn validate_manifest(m: &Manifest, c: &Config) -> Result<()> {
    if ![FORMAT, FORMAT_V2].contains(&m.format.as_str())
        || m.cluster_id != c.cluster_id
        || m.ledger_id != c.ledger_id
        || m.inventory["ledger_id"] != c.ledger_id
        || m.generation == 0
        || m.generation > i64::MAX as u64
        || m.files.len() > 20000
    {
        return fail(409, "CLUSTER_IDENTITY_OR_SNAPSHOT_INVALID");
    }
    for required in ["ledger.sqlite3", "auth.sqlite3", "outputs.sqlite3"] {
        if !m.files.contains_key(required) {
            return fail(422, "CLUSTER_SNAPSHOT_INCOMPLETE");
        }
    }
    let mut total = 0u64;
    for (name, entry) in &m.files {
        if !valid_name(name) || !hex(&entry.sha256) || entry.size > FILE_LIMIT {
            return fail(422, "CLUSTER_FILE_INVALID");
        }
        total = total
            .checked_add(entry.size)
            .ok_or_else(|| Error::new(413, "CLUSTER_SNAPSHOT_TOO_LARGE"))?;
    }
    if total > TOTAL_LIMIT {
        return fail(413, "CLUSTER_SNAPSHOT_TOO_LARGE");
    }
    Ok(())
}
pub fn validate_data(folder: &Path, m: &Manifest) -> Result<()> {
    for (name, entry) in &m.files {
        let path = folder.join(name);
        if path.metadata()?.len() != entry.size || files::sha(&path)? != entry.sha256 {
            return fail(422, "CLUSTER_FILE_HASH_INVALID");
        }
    }
    let ledger = folder.join("ledger.sqlite3");
    if integrity::inventory(&store::open(&ledger, false)?)? != m.inventory {
        return fail(422, "CLUSTER_LEDGER_INVENTORY_INVALID");
    }
    let auth = Auth::open(folder.join("auth.sqlite3"))?;
    let v2 = crate::automatic::schema::enabled(&auth.connection()?)?;
    if v2 != (m.format == FORMAT_V2) {
        return fail(409, "CLUSTER_AUTH_PROTOCOL_CONFLICT");
    }
    backup::accounts(&ledger, &auth)?;
    if m.files.contains_key("devices.sqlite3") {
        Devices::open(folder.join("devices.sqlite3"))?.validate_accounts(&auth)?;
    }
    let outputs = Outputs::open(folder.join("outputs.sqlite3"), &m.ledger_id)?;
    let expected = outputs
        .validate_ledger(&ledger)?
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>();
    let actual = m
        .files
        .keys()
        .filter(|n| n.starts_with("output-blobs/"))
        .cloned()
        .collect::<std::collections::BTreeSet<_>>();
    if actual != expected {
        return fail(422, "CLUSTER_OUTPUT_BINDING_INVALID");
    }
    Ok(())
}
pub fn publish(root: &Path, stage: &Path, m: &Manifest) -> Result<Publication> {
    validate_manifest(m, &config::required(root)?)?;
    let raw = serde_json::to_vec(m)?;
    if raw.len() > MANIFEST_LIMIT {
        return fail(413, "CLUSTER_MANIFEST_TOO_LARGE");
    }
    let p = Publication {
        generation: m.generation,
        sha256: store::hash(&raw),
    };
    if let Some(old) = current(root)? {
        if old.generation > p.generation {
            return fail(409, "CLUSTER_SOURCE_ROLLBACK");
        }
        if old.generation == p.generation {
            if old.sha256 != p.sha256 {
                return fail(409, "CLUSTER_GENERATION_CONFLICT");
            }
            return Ok(old);
        }
    }
    validate_data(stage, m)?;
    let final_path = folder(root, &p)?;
    if !final_path.exists() {
        files::new_file(&stage.join("manifest.json"), &raw)?;
        fs::rename(stage, &final_path)?;
    } else {
        // A process may have exited after finalizing this directory but before publishing.
        validate_data(&final_path, m)?;
        if files::read(&final_path.join("manifest.json"), MANIFEST_LIMIT)? != raw {
            return fail(409, "CLUSTER_GENERATION_CONFLICT");
        }
    }
    files::replace_json(
        &config::directory(root).join("current.json"),
        &serde_json::to_value(&p)?,
    )?;
    prune(root, &p)?;
    Ok(p)
}
pub fn capture(s: &Service, c: &Config) -> Result<Option<Publication>> {
    clean_stages(&s.root, "capture-")?;
    let old = current(&s.root)?;
    if let Some(p) = &old {
        prune(&s.root, p)?;
    }
    let generation = old.as_ref().map(|p| p.generation + 1).unwrap_or(1);
    let stage = config::directory(&s.root).join(format!("capture-{}", store::uid()?));
    files::new_dir(&stage)?;
    let result = (|| {
        let inventory = integrity::backup(&s.ledger, &stage.join("ledger.sqlite3"))?;
        files::snapshot(
            &s.auth.path,
            &stage.join("auth.sqlite3"),
            crate::auth::APP,
            crate::auth::DDL,
        )?;
        let mut names = vec!["ledger.sqlite3".to_owned(), "auth.sqlite3".to_owned()];
        if let Some(d) = &s.devices {
            files::snapshot(
                &d.path,
                &stage.join("devices.sqlite3"),
                crate::devices::APP,
                crate::devices::DDL,
            )?;
            names.push("devices.sqlite3".into());
        }
        let outputs = s
            .outputs
            .as_ref()
            .ok_or_else(|| Error::new(409, "CLUSTER_OUTPUT_STORE_REQUIRED"))?;
        names.extend(outputs.backup(&stage)?);
        let mut entries = BTreeMap::new();
        for name in names {
            let path = stage.join(&name);
            entries.insert(
                name,
                FileEntry {
                    size: path.metadata()?.len(),
                    sha256: files::sha(&path)?,
                },
            );
        }
        let m = Manifest {
            format: if crate::automatic::schema::enabled(&s.auth.connection()?)? {
                FORMAT_V2
            } else {
                FORMAT
            }
            .into(),
            cluster_id: c.cluster_id.clone(),
            ledger_id: c.ledger_id.clone(),
            generation,
            inventory,
            files: entries,
        };
        validate_manifest(&m, c)?;
        if let Some(old) = old {
            if read(&s.root, &old)?.files == m.files {
                return Ok(None);
            }
        }
        let result = publish(&s.root, &stage, &m)?;
        quote_diagnostics::event(
            "cluster.snapshot.published",
            json!({"generation":result.generation,"files":m.files.len()}),
        );
        Ok(Some(result))
    })();
    if stage.exists() {
        let _ = fs::remove_dir_all(&stage);
    }
    result
}
pub fn chunk(root: &Path, p: &Publication, name: &str, offset: u64) -> Result<Value> {
    let m = read(root, p)?;
    let entry = m
        .files
        .get(name)
        .ok_or_else(|| Error::new(404, "CLUSTER_FILE_NOT_FOUND"))?;
    if offset > entry.size {
        return fail(422, "CLUSTER_CHUNK_OFFSET_INVALID");
    }
    let mut file = fs::File::open(folder(root, p)?.join(name))?;
    file.seek(SeekFrom::Start(offset))?;
    let mut raw = vec![];
    file.take(CHUNK as u64).read_to_end(&mut raw)?;
    use base64::{engine::general_purpose::STANDARD, Engine};
    Ok(
        json!({"generation":p.generation,"manifest":p.sha256,"offset":offset,"sha256":entry.sha256,"data":STANDARD.encode(raw)}),
    )
}
fn prune(root: &Path, current: &Publication) -> Result<()> {
    let retained = if config::required(root)?.role == config::Role::Primary {
        super::membership::retained(root)?
    } else {
        Default::default()
    };
    let mut candidates = Vec::new();
    for entry in fs::read_dir(generations(root))? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let Some((number, sha)) = name.split_once('_') else {
            continue;
        };
        if number.len() != 20 || !hex(sha) || !entry.file_type()?.is_dir() {
            continue;
        }
        let Ok(generation) = number.parse::<u64>() else {
            continue;
        };
        candidates.push((generation, sha.to_owned(), entry.path()));
    }
    let previous = candidates
        .iter()
        .filter(|(g, _, _)| *g < current.generation)
        .map(|(g, _, _)| *g)
        .max();
    let mut kept_previous = false;
    for (g, sha, path) in candidates {
        if (g == current.generation && sha == current.sha256) || retained.contains(&(g, sha)) {
            continue;
        }
        if Some(g) == previous && !kept_previous {
            kept_previous = true;
            continue;
        }
        let _ = fs::remove_dir_all(path);
    }
    Ok(())
}

/// Called only while this root's exclusive owner is held; only protocol names.
pub fn clean_stages(root: &Path, prefix: &str) -> Result<()> {
    for entry in fs::read_dir(config::directory(root))? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if name
            .strip_prefix(prefix)
            .is_some_and(|id| store::id(id).is_ok())
            && entry.file_type()?.is_dir()
        {
            files::dir(&entry.path())?;
            fs::remove_dir_all(entry.path())?;
        }
    }
    Ok(())
}
