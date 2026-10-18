use super::{
    config::{self, Role},
    snapshot::{self, Manifest, Publication},
    transport::Peer,
};
use crate::{fail, files, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::store;
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
pub fn data_directory(root: &Path) -> Result<PathBuf> {
    if let Some(c) = config::read(root)? {
        if c.role == Role::Replica {
            let p = snapshot::current(root)?
                .ok_or_else(|| Error::new(503, "CLUSTER_INITIAL_SYNC_REQUIRED"))?;
            return snapshot::folder(root, &p);
        }
    }
    Ok(root.join("private"))
}
pub fn status(root: &Path, phase: &str, generation: u64, error: Option<&str>) -> Result<()> {
    let path = config::directory(root).join("status.json");
    let old = if path.exists() {
        files::read_json(&path)?
    } else {
        Value::Null
    };
    let at = crate::auth::now();
    let changed =
        old["phase"] != phase || old["generation"] != generation || old["error"] != json!(error);
    if changed || at - old["last_contact"].as_i64().unwrap_or(0) >= 10 {
        files::replace_json(
            &path,
            &json!({"phase":phase,"generation":generation,"last_contact":at,"error":error}),
        )?;
    }
    if changed {
        quote_diagnostics::event(
            "cluster.state.changed",
            json!({"phase":phase,"generation":generation,"error":error}),
        );
    }
    Ok(())
}
fn ensure_directory(path: &Path) -> Result<()> {
    if !path.exists() {
        files::new_dir(path)?;
    }
    Ok(())
}
fn cache_file(root: &Path, sha: &str) -> PathBuf {
    config::directory(root).join("cache").join(sha)
}
async fn download(
    peer: &Peer,
    root: &Path,
    p: &Publication,
    name: &str,
    entry: &snapshot::FileEntry,
    stop: &AtomicBool,
) -> Result<PathBuf> {
    let complete = cache_file(root, &entry.sha256);
    if complete.exists() {
        if complete.metadata()?.len() == entry.size && files::sha(&complete)? == entry.sha256 {
            return Ok(complete);
        }
        fs::remove_file(&complete)?;
    }
    let partial = complete.with_extension("partial");
    let mut file = if partial.exists() {
        fs::OpenOptions::new().append(true).open(&partial)?
    } else {
        files::new_file(&partial, &[])?;
        fs::OpenOptions::new().append(true).open(&partial)?
    };
    let mut offset = file.metadata()?.len();
    if offset > entry.size {
        drop(file);
        fs::remove_file(partial)?;
        return fail(409, "CLUSTER_PARTIAL_INVALID");
    }
    while offset < entry.size {
        if stop.load(Ordering::SeqCst) {
            return fail(503, "CLUSTER_SYNC_STOPPED");
        }
        let value = peer
            .request(
                "/v1/cluster/chunk",
                json!({"generation":p.generation,"manifest":p.sha256,"name":name,"offset":offset}),
            )
            .await?;
        if value["generation"] != p.generation
            || value["manifest"] != p.sha256
            || value["offset"] != offset
            || value["sha256"] != entry.sha256
        {
            return fail(409, "CLUSTER_CHUNK_IDENTITY_CONFLICT");
        }
        let raw = STANDARD
            .decode(
                value["data"]
                    .as_str()
                    .ok_or_else(|| Error::new(422, "CLUSTER_CHUNK_INVALID"))?,
            )
            .map_err(|_| Error::new(422, "CLUSTER_CHUNK_INVALID"))?;
        if raw.is_empty() || raw.len() > snapshot::CHUNK || offset + raw.len() as u64 > entry.size {
            return fail(422, "CLUSTER_CHUNK_INVALID");
        }
        file.write_all(&raw)?;
        file.sync_data()?;
        offset += raw.len() as u64;
    }
    file.sync_all()?;
    drop(file);
    if files::sha(&partial)? != entry.sha256 {
        fs::remove_file(&partial)?;
        return fail(422, "CLUSTER_FILE_HASH_INVALID");
    }
    fs::rename(&partial, &complete)?;
    Ok(complete)
}
pub async fn synchronize(peer: &Peer, root: &Path, stop: &AtomicBool) -> Result<Publication> {
    let value = peer.request("/v1/cluster/manifest", json!({})).await?;
    let p: Publication = serde_json::from_value(value["publication"].clone())?;
    let m: Manifest = serde_json::from_value(value["manifest"].clone())?;
    snapshot::validate_manifest(&m, &peer.config)?;
    if p.generation != m.generation || store::hash(serde_json::to_vec(&m)?) != p.sha256 {
        return fail(409, "CLUSTER_MANIFEST_HASH_INVALID");
    }
    if let Some(old) = snapshot::current(root)? {
        if old.generation > p.generation {
            return fail(409, "CLUSTER_SOURCE_ROLLBACK");
        }
        if old.generation == p.generation {
            if old.sha256 != p.sha256 {
                return fail(409, "CLUSTER_GENERATION_CONFLICT");
            }
            peer.request(
                "/v1/cluster/ack",
                json!({"generation":p.generation,"manifest":p.sha256}),
            )
            .await?;
            status(root, "synced", p.generation, None)?;
            return Ok(p);
        }
    }
    snapshot::clean_stages(root, "stage-")?;
    clean_cache(root, &m)?;
    status(
        root,
        "catching_up",
        snapshot::current(root)?.map(|p| p.generation).unwrap_or(0),
        None,
    )?;
    ensure_directory(&config::directory(root).join("cache"))?;
    ensure_directory(&snapshot::generations(root))?;
    let stage = config::directory(root).join(format!("stage-{}", store::uid()?));
    files::new_dir(&stage)?;
    files::new_dir(&stage.join("output-blobs"))?;
    let result = async {
        for (name, entry) in &m.files {
            if stop.load(Ordering::SeqCst) {
                return fail(503, "CLUSTER_SYNC_STOPPED");
            }
            let cached = download(peer, root, &p, name, entry, stop).await?;
            let target = stage.join(name);
            // Copies keep SQLite inspection separate from the content-addressed cache.
            fs::copy(cached, &target)?;
            fs::OpenOptions::new()
                .write(true)
                .open(&target)?
                .sync_all()?;
        }
        let publication = snapshot::publish(root, &stage, &m)?;
        peer.request(
            "/v1/cluster/ack",
            json!({"generation":publication.generation,"manifest":publication.sha256}),
        )
        .await?;
        status(root, "synced", publication.generation, None)?;
        quote_diagnostics::event(
            "cluster.sync.applied",
            json!({"generation":publication.generation,"files":m.files.len()}),
        );
        Ok(publication)
    }
    .await;
    if stage.exists() {
        let _ = fs::remove_dir_all(&stage);
    }
    result
}
pub async fn run(peer: Arc<Peer>, root: PathBuf, stop: Arc<AtomicBool>) {
    while !stop.load(Ordering::SeqCst) {
        if let Err(error) = synchronize(&peer, &root, &stop).await {
            if stop.load(Ordering::SeqCst) {
                break;
            }
            let phase = if error.code == "CLUSTER_PEER_REVOKED" {
                "revoked"
            } else {
                "disconnected"
            };
            let generation = snapshot::current(&root)
                .ok()
                .flatten()
                .map(|p| p.generation)
                .unwrap_or(0);
            let _ = status(&root, phase, generation, Some(&error.code));
        }
        for _ in 0..20 {
            if stop.load(Ordering::SeqCst) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
}
pub fn inspect(root: &Path) -> Result<Value> {
    let Some(c) = config::read(root)? else {
        return Ok(json!({"mode":"standalone","synchronization":"not_enabled"}));
    };
    let publication = snapshot::current(root)?;
    let path = config::directory(root).join("status.json");
    let mut state = if path.exists() {
        files::read_json(&path)?
    } else {
        json!({"phase":if c.role==Role::Primary{"primary"}else{"joining"}})
    };
    if c.role == Role::Replica
        && state["phase"] == "synced"
        && crate::auth::now() - state["last_contact"].as_i64().unwrap_or(0) > 30
    {
        state["phase"] = json!("contact_not_confirmed");
    }
    Ok(
        json!({"protocol":config::FORMAT,"cluster_id":c.cluster_id,"ledger_id":c.ledger_id,"node_id":c.node_id,"role":c.role,"current":publication,"state":state,"write_authority":"primary_only","acknowledgement":"primary_local_then_async_replication","automatic_failover":false,"peers":if c.role==Role::Primary{super::membership::listing(root)?}else{json!([])}}),
    )
}

fn clean_cache(root: &Path, incoming: &Manifest) -> Result<()> {
    let cache = config::directory(root).join("cache");
    if !cache.exists() {
        return Ok(());
    }
    let mut hashes = incoming
        .files
        .values()
        .map(|f| f.sha256.clone())
        .collect::<std::collections::BTreeSet<_>>();
    if let Some(p) = snapshot::current(root)? {
        hashes.extend(
            snapshot::read(root, &p)?
                .files
                .values()
                .map(|f| f.sha256.clone()),
        );
    }
    for entry in fs::read_dir(cache)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let sha = name.strip_suffix(".partial").unwrap_or(&name);
        if snapshot::hex(sha) && !hashes.contains(sha) && entry.file_type()?.is_file() {
            fs::remove_file(entry.path())?;
        }
    }
    Ok(())
}
