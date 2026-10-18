use crate::{
    automatic::*,
    cluster::{
        config::{self, Config, Role},
        replica, snapshot,
        transport::Peer,
    },
    host::{self, Init},
    service::Service,
    Result,
};
use quote_security::automatic::Package;
use serde_json::{json, Value};
use std::{
    path::Path,
    sync::atomic::{AtomicBool, Ordering},
};
pub async fn join(init: Init, state: &Path, package: &Path) -> Result<Value> {
    join_with_stop(init, state, package, &AtomicBool::new(false)).await
}
pub async fn join_with_stop(
    init: Init,
    state: &Path,
    package: &Path,
    stop: &AtomicBool,
) -> Result<Value> {
    let p: Package = serde_json::from_slice(&files::read(package, 131072)?)?;
    let connection = p
        .validate("manager")
        .map_err(|e| crate::Error::new(e.status, &e.code))?;
    let caps: Vec<String> = serde_json::from_value(p.manifest["capabilities"].clone())?;
    permissions::validate("manager", &caps)?;
    let root = init.root.clone();
    let auxiliary = init.auxiliary;
    if let Some(c) = config::read(&root)? {
        if !state.join("node.bin").exists() || root.join("private/deployment.json").exists() {
            deployment::verify(&root, auxiliary)?;
        }
        if c.ledger_id != p.profile["ledger_id"]
            || c.primary.certificate_sha256 != connection.certificate_sha256
        {
            return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
        }
        if c.role == Role::Primary {
            deployment::verify(&root, auxiliary)?;
            let profile =
                trust::profile(&Service::load(&root, auxiliary, true)?.auth.connection()?)?;
            if profile != p.profile {
                return crate::fail(409, "AUTOMATIC_SITE_CONFLICT");
            }
            return Ok(json!({"status":"primary_reused","ledger_id":c.ledger_id}));
        }
    } else if root.exists() {
        return crate::fail(409, "CLUSTER_JOIN_REQUIRES_NEW_ROOT");
    }
    if !state.exists() {
        files::new_dir(state)?;
    }
    files::dir(state)?;
    let node = super::identity::enroll(state, &root, &p, auxiliary).await?;
    if stop.load(Ordering::SeqCst) {
        return crate::fail(503, "CLUSTER_SYNC_STOPPED");
    }
    let id = node["node_id"].as_str().ok_or_else(denied)?;
    if !root.exists() {
        // The live path is published only after it is permanently marked replica.
        let stage = super::staging::initialize(&init, state, id)?;
        // An interrupted initialization is preserved; only a fully validated stage advances.
        if config::read(&stage)?.is_none() {
            Service::load(&stage, auxiliary, false)?;
        } else {
            let cfg = files::read_json(&stage.join("private/service.json"))?;
            host::validate_resources(&stage.join("private"), &cfg)?;
            let staged = config::required(&stage)?;
            if staged.node_id != id || staged.ledger_id != p.profile["ledger_id"] {
                return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
            }
        }
        let dir = config::directory(&stage);
        if !dir.exists() {
            files::new_dir(&dir)?;
        }
        let c = Config {
            format: config::FORMAT.into(),
            cluster_id: node["joined"]["cluster_id"]
                .as_str()
                .ok_or_else(denied)?
                .into(),
            ledger_id: p.profile["ledger_id"].as_str().ok_or_else(denied)?.into(),
            node_id: id.into(),
            role: Role::Replica,
            primary: connection.clone(),
        };
        if !dir.join("peer.bin").exists() {
            config::save_secret(
                &stage,
                node["secret"].as_str().ok_or_else(denied)?,
                auxiliary,
            )?;
        }
        files::replace_json(&dir.join("config.json"), &serde_json::to_value(c)?)?;
        let mut template = files::read_json(&stage.join("client-template.json"))?;
        template["certificate"] = json!(root.join("service-cert.pem"));
        files::replace_json(&stage.join("client-template.json"), &template)?;
        std::fs::rename(stage, &root)?;
    }
    let _owner = files::Owner::acquire(&root)?;
    let c = config::required(&root)?;
    if c.node_id != id
        || c.role != Role::Replica
        || c.primary.certificate_sha256 != connection.certificate_sha256
    {
        return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    // Copy program resources only after local runner ownership was established by installation.
    let private = root.join("private");
    let candidate_hash = files::sha(&std::env::current_exe()?)?;
    let current_hash = files::sha(&private.join("rust-service-host.exe"))?;
    let mut s = files::read_json(&private.join("service.json"))?;
    if current_hash != candidate_hash && s["rust_host_sha256"] != current_hash {
        return crate::fail(409, "HOST_RESOURCE_IDENTITY_CONFLICT");
    }
    if current_hash != candidate_hash {
        deployment::replace_file(
            &std::env::current_exe()?,
            &private.join("rust-service-host.exe"),
        )?;
    }
    s["rust_host_sha256"] = json!(candidate_hash);
    files::replace_json(&private.join("service.json"), &s)?;
    if !snapshot::generations(&root).exists() {
        files::new_dir(&snapshot::generations(&root))?;
    }
    let peer = Peer::new(&c, config::secret(&root, auxiliary)?)?;
    let publication = replica::synchronize(&peer, &root, stop).await?;
    let manifest = snapshot::read(&root, &publication)?;
    let mut service = files::read_json(&private.join("service.json"))?;
    service["ledger_id"] = json!(c.ledger_id);
    if manifest.files.contains_key("devices.sqlite3") {
        service["device_auth"] = json!(crate::devices::FORMAT);
    }
    files::replace_json(&private.join("service.json"), &service)?;
    Service::load(&root, auxiliary, false)?;
    Ok(
        json!({"status":"replica_ready","node_id":c.node_id,"generation":publication.generation,"ledger_id":c.ledger_id}),
    )
}
