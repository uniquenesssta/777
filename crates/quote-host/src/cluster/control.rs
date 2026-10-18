use super::{
    config::{self, Config, Role},
    membership, replica, snapshot,
    transport::{Client, Peer},
};
use crate::{
    auth::Auth,
    fail, files,
    host::{self, Init},
    service::Service,
    Error, Result,
};
use quote_ledger::{integrity, store};
use quote_security::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{fs, path::Path, sync::atomic::AtomicBool};
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Invitation {
    pub format: String,
    pub cluster_id: String,
    pub ledger_id: String,
    pub primary: Connection,
    pub grant_id: String,
    pub ticket: String,
    pub expires: i64,
}
fn directory(path: &Path) -> Result<()> {
    if !path.exists() {
        files::new_dir(path)?;
    }
    Ok(())
}
pub fn primary(root: &Path, user: &str, password: &str, auxiliary: bool) -> Result<Value> {
    let _owner = files::Owner::acquire(root)?;
    if config::read(root)?.is_some_and(|c| c.role == Role::Replica) {
        return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
    }
    let mut service = Service::load(root, auxiliary, true)?;
    if files::sha(&std::env::current_exe()?)? != service.config["rust_host_sha256"] {
        return fail(409, "CLUSTER_HOST_RESOURCE_UPGRADE_REQUIRED");
    }
    let login = service
        .auth
        .login(&json!(user), &json!(password), "cluster-primary")?;
    let token = login["token"].as_str().unwrap();
    let result = (|| {
        Auth::admin(&service.auth.authenticate(token)?)?;
        let c = if let Some(c) = config::read(root)? {
            if c.role != Role::Primary || service.config["ledger_id"] != c.ledger_id {
                return fail(409, "CLUSTER_IDENTITY_CONFLICT");
            }
            c
        } else {
            directory(&config::directory(root))?;
            let c = Config {
                format: config::FORMAT.into(),
                cluster_id: store::uid()?,
                ledger_id: service.config["ledger_id"].as_str().unwrap().into(),
                node_id: store::uid()?,
                role: Role::Primary,
                primary: config::connection(root)?,
            };
            files::new_file(
                &config::directory(root).join("config.json"),
                &serde_json::to_vec(&c)?,
            )?;
            c
        };
        if !config::directory(root).join("peers.sqlite3").exists() {
            membership::create(root)?;
        }
        directory(&snapshot::generations(root))?;
        Ok(c)
    })();
    let _ = service.auth.logout(token);
    let c = result?;
    snapshot::capture(&service, &c)?;
    quote_diagnostics::event(
        "cluster.primary.enabled",
        json!({"cluster_id":c.cluster_id,"ledger_id":c.ledger_id}),
    );
    replica::inspect(root)
}
pub async fn admin(
    root: &Path,
    user: &str,
    password: &str,
    path: &str,
    body: Value,
) -> Result<Value> {
    let config = config::ensure_primary(root)?;
    let client = Client::new(&config.primary)?;
    let login = client
        .request(
            "/v1/login",
            "",
            &json!({"username":user,"password":password}),
        )
        .await?;
    let token = login["token"]
        .as_str()
        .ok_or_else(|| Error::new(502, "CLUSTER_RESPONSE_INVALID"))?;
    let result = client.request(path, token, &body).await;
    let _ = client.request("/v1/logout", token, &json!({})).await;
    result
}
fn invitation(path: &Path) -> Result<Invitation> {
    let value: Invitation = serde_json::from_slice(&files::read(path, 131072)?)?;
    if value.format != "777-cluster-invitation-v1" {
        return fail(422, "CLUSTER_INVITATION_INVALID");
    }
    for id in [&value.cluster_id, &value.ledger_id, &value.grant_id] {
        store::id(id)?;
    }
    membership::validate_secret(&value.ticket)?;
    quote_security::tls::configuration(&value.primary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    Ok(value)
}
pub async fn join(mut init: Init, invitation_path: Option<&Path>) -> Result<Value> {
    let root = init.root.clone();
    let auxiliary = init.auxiliary;
    let fresh = !root.exists();
    // Existing standalone data is never adopted or replaced by a join operation.
    if !fresh && !config::directory(&root).join("joining.bin").exists() {
        if let Some(c) = config::read(&root)? {
            if c.role == Role::Replica {
                if let Some(path) = invitation_path {
                    let other = invitation(path)?;
                    if other.cluster_id != c.cluster_id
                        || other.ledger_id != c.ledger_id
                        || other.primary.certificate_sha256 != c.primary.certificate_sha256
                    {
                        return fail(409, "CLUSTER_IDENTITY_CONFLICT");
                    }
                }
                return replica::inspect(&root);
            }
        }
        return fail(409, "CLUSTER_JOIN_REQUIRES_NEW_ROOT");
    }
    let supplied = invitation_path.map(invitation).transpose()?;
    if fresh {
        let invite = supplied
            .as_ref()
            .ok_or_else(|| Error::new(422, "CLUSTER_INVITATION_REQUIRED"))?;
        // Publish a fully resumable bootstrap in one directory rename. A crash
        // during initialization never leaves the selected root half initialized.
        let bootstrap = root.with_file_name(format!(".777-join-{}", store::uid()?));
        init.root = bootstrap.clone();
        init.secret = membership::credential()?;
        let prepared = (|| {
            host::initialize(init)?;
            directory(&config::directory(&bootstrap))?;
            let c = Config {
                format: config::FORMAT.into(),
                cluster_id: invite.cluster_id.clone(),
                ledger_id: invite.ledger_id.clone(),
                node_id: store::uid()?,
                role: Role::Replica,
                primary: invite.primary.clone(),
            };
            config::save_secret(&bootstrap, &membership::credential()?, auxiliary)?;
            let protected =
                quote_security::protect::protect(&serde_json::to_vec(invite)?, true, auxiliary)
                    .map_err(|e| Error::new(e.status, &e.code))?;
            files::new_file(
                &config::directory(&bootstrap).join("joining.bin"),
                &protected,
            )?;
            files::new_file(
                &config::directory(&bootstrap).join("config.json"),
                &serde_json::to_vec(&c)?,
            )?;
            let template = bootstrap.join("client-template.json");
            let mut value = files::read_json(&template)?;
            value["certificate"] = json!(root.join("service-cert.pem"));
            files::replace_json(&template, &value)?;
            if root.exists() {
                return fail(409, "CLUSTER_JOIN_REQUIRES_NEW_ROOT");
            }
            fs::rename(&bootstrap, &root)?;
            Ok(())
        })();
        if prepared.is_err() && bootstrap.exists() {
            let _ = fs::remove_dir_all(&bootstrap);
        }
        prepared?;
    }
    let _owner = files::Owner::acquire(&root)?;
    let c = config::required(&root)?;
    if c.role != Role::Replica {
        return fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    let pending = config::directory(&root).join("joining.bin");
    let raw = quote_security::protect::protect(&files::read(&pending, 262144)?, false, auxiliary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    let invite: Invitation = serde_json::from_slice(&raw)?;
    if let Some(other) = supplied {
        if other.cluster_id != invite.cluster_id
            || other.ledger_id != invite.ledger_id
            || other.primary.certificate_sha256 != invite.primary.certificate_sha256
        {
            return fail(409, "CLUSTER_IDENTITY_CONFLICT");
        }
    }
    let secret = config::secret(&root, auxiliary)?;
    let client = Client::new(&c.primary)?;
    let response=client.request("/v1/cluster/enroll","",&json!({"cluster_id":c.cluster_id,"ledger_id":c.ledger_id,"grant_id":invite.grant_id,"ticket":invite.ticket,"node_id":c.node_id,"credential":secret})).await?;
    if response["cluster_id"] != c.cluster_id
        || response["ledger_id"] != c.ledger_id
        || response["node_id"] != c.node_id
    {
        return fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    directory(&snapshot::generations(&root))?;
    let peer = Peer::new(&c, secret)?;
    let p = replica::synchronize(&peer, &root, &AtomicBool::new(false)).await?;
    let manifest = snapshot::read(&root, &p)?;
    let path = root.join("private/service.json");
    let mut service = files::read_json(&path)?;
    service["ledger_id"] = json!(c.ledger_id);
    if manifest.files.contains_key("devices.sqlite3") {
        service["device_auth"] = json!(crate::devices::FORMAT);
    } else {
        service.as_object_mut().unwrap().remove("device_auth");
    }
    files::replace_json(&path, &service)?;
    let check = Service::load(&root, auxiliary, false)?;
    if integrity::inventory(&store::open(&check.ledger, false)?)? != manifest.inventory {
        return fail(503, "CLUSTER_JOIN_INVENTORY_CONFLICT");
    }
    fs::remove_file(pending)?;
    quote_diagnostics::event(
        "cluster.join.completed",
        json!({"cluster_id":c.cluster_id,"node_id":c.node_id,"generation":p.generation}),
    );
    Ok(
        json!({"status":"joined_stopped","root":root,"cluster":replica::inspect(&root)?,"inventory":manifest.inventory,"certificate_sha256":check.config["certificate_sha256"]}),
    )
}
