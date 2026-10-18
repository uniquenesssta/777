//! Offline upgrade journal: preserve the existing ledger, account, TLS and backups.
pub use super::kit::Kit;
use super::*;
use crate::service::Service;
use std::path::Path;
pub fn apply(root: &Path, kit_path: &Path, notices: &Path, auxiliary: bool) -> Result<Value> {
    deployment::verify(root, auxiliary)?;
    let _owner = files::Owner::acquire(root)?;
    let kit: Kit = serde_json::from_slice(&files::read(kit_path, 256 * 1024)?)?;
    kit.validate()?;
    let mut d = deployment::verify(root, auxiliary)?;
    let private = root.join("private");
    let candidate = files::sha(&std::env::current_exe()?)?;
    let saved_host = files::sha(&private.join("rust-service-host.exe"))?;
    let config_path = private.join("service.json");
    let mut config = files::read_json(&config_path)?;
    if config["bind"] != "192.168.4.23"
        || config["port"] != 8477
        || d["ledger_id"] != config["ledger_id"]
    {
        return fail(409, "AUTOMATIC_PRIMARY_ENDPOINT_CONFLICT");
    }
    if crate::cluster::config::read(root)?
        .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
    {
        return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
    }
    let journal = private.join("automatic-upgrade.json");
    if journal.exists() {
        let old = files::read_json(&journal)?;
        if old["candidate"] != candidate && old["completed"] == true {
            std::fs::rename(
                &journal,
                private.join(format!("automatic-upgrade-{}.json", store::uid()?)),
            )?;
        }
    }
    let connection = crate::cluster::config::connection(root)?;
    if connection.url.trim_end_matches('/') != trust::PRIMARY
        || connection.certificate_sha256 != config["certificate_sha256"]
    {
        return fail(409, "AUTOMATIC_SITE_CONFLICT");
    }
    quote_security::tls::configuration(&connection).map_err(|e| Error::new(e.status, &e.code))?;
    if let Some(cluster) = crate::cluster::config::read(root)? {
        if cluster.ledger_id != config["ledger_id"]
            || cluster.primary.url.trim_end_matches('/') != trust::PRIMARY
            || cluster.primary.certificate_sha256 != connection.certificate_sha256
        {
            return fail(409, "CLUSTER_IDENTITY_CONFLICT");
        }
    }
    if !journal.exists() {
        Service::load(root, auxiliary, true)?;
        if d["host_sha256"] != saved_host {
            return fail(409, "HOST_DEPLOYMENT_RESOURCE_CHANGED");
        }
        deployment::retain(
            &private.join("rust-service-host.exe"),
            &private.join(format!("host-before-{}.exe", kit.upgrade_id)),
        )?;
        deployment::retain(
            &config_path,
            &private.join(format!("service-before-{}.json", kit.upgrade_id)),
        )?;
        deployment::retain(
            &private.join("deployment.json"),
            &private.join(format!("deployment-before-{}.json", kit.upgrade_id)),
        )?;
        files::new_file(
            &journal,
            &serde_json::to_vec(
                &json!({"upgrade_id":kit.upgrade_id,"candidate":candidate,"previous_host":saved_host,"ledger_id":config["ledger_id"],"certificate_sha256":config["certificate_sha256"]}),
            )?,
        )?;
    }
    let j = files::read_json(&journal)?;
    if j["candidate"] != candidate
        || j["ledger_id"] != config["ledger_id"]
        || j["certificate_sha256"] != config["certificate_sha256"]
        || saved_host != j["previous_host"] && saved_host != candidate
    {
        return fail(409, "UPGRADE_RESOURCE_IDENTITY_CONFLICT");
    }
    // Rebind with a newly prepared kit after expiry, using the same compatible executable.
    if files::sha(&private.join("tls-cert.pem"))? != files::sha(&root.join("service-cert.pem"))?
        || crate::host::certificate_sha(&private.join("tls-cert.pem"))?
            != config["certificate_sha256"]
    {
        return fail(409, "CERTIFICATE_IDENTITY_CONFLICT");
    }
    let inv =
        quote_ledger::integrity::inventory(&store::open(&private.join("ledger.sqlite3"), false)?)?;
    if inv["ledger_id"] != config["ledger_id"] {
        return fail(409, "HOST_STORE_IDENTITY_CONFLICT");
    }
    // Verify all other resources even when recovering between exe/config publication.
    let mut validated = config.clone();
    validated["rust_host_sha256"] = json!(saved_host);
    crate::host::validate_resources(&private, &validated)?;
    schema::upgrade(&private.join("auth.sqlite3"))?;
    deployment::replace_file(
        &std::env::current_exe()?,
        &private.join("rust-service-host.exe"),
    )?;
    deployment::replace_file(notices, &private.join("rust-host-notices.txt"))?;
    config["rust_host_sha256"] = json!(candidate);
    files::replace_json(&config_path, &config)?;
    d["host_sha256"] = json!(candidate);
    files::replace_json(&private.join("deployment.json"), &d)?;
    let mut s = Service::load(root, auxiliary, true)?;
    let c = s.auth.connection()?;
    let p = trust::install(
        &c,
        config["ledger_id"].as_str().ok_or_else(denied)?,
        &connection,
        &kit,
    )?;
    ensure_cluster(&mut s, &connection)?;
    let expires: i64 = c.query_row(
        "SELECT expires FROM upgrade_bindings WHERE id=?",
        [&kit.upgrade_id],
        |r| r.get(0),
    )?;
    let pair = private.join("automatic-pair.bin");
    issuer_state::save(
        &pair,
        &json!({"kit":kit,"expires":expires.min(auth::now()+1800)}),
        auxiliary,
    )?;
    audit(
        &c,
        "local-owner",
        "host.upgraded",
        p["site_id"].as_str().ok_or_else(denied)?,
    )?;
    let mut completed = j;
    completed["completed"] = json!(true);
    files::replace_json(&journal, &completed)?;
    Ok(
        json!({"status":"upgraded_restart_required","site_id":p["site_id"],"ledger_id":p["ledger_id"],"existing_data":"preserved"}),
    )
}
fn ensure_cluster(s: &mut Service, connection: &quote_security::Connection) -> Result<()> {
    use crate::cluster::{
        config::{self, Config, Role},
        membership, snapshot,
    };
    let directory = config::directory(&s.root);
    if !directory.exists() {
        files::new_dir(&directory)?;
    }
    let c = if let Some(c) = config::read(&s.root)? {
        if c.role != Role::Primary
            || c.ledger_id != s.config["ledger_id"]
            || c.primary.certificate_sha256 != connection.certificate_sha256
        {
            return fail(409, "CLUSTER_IDENTITY_CONFLICT");
        }
        c
    } else {
        let c = Config {
            format: config::FORMAT.into(),
            cluster_id: store::uid()?,
            ledger_id: s.config["ledger_id"].as_str().ok_or_else(denied)?.into(),
            node_id: store::uid()?,
            role: Role::Primary,
            primary: connection.clone(),
        };
        files::new_file(&directory.join("config.json"), &serde_json::to_vec(&c)?)?;
        c
    };
    if !directory.join("peers.sqlite3").exists() {
        membership::create(&s.root)?;
    }
    if !snapshot::generations(&s.root).exists() {
        files::new_dir(&snapshot::generations(&s.root))?;
    }
    snapshot::capture(s, &c)?;
    Ok(())
}
