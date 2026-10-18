use crate::{fail, files, Error, Result};
use quote_ledger::store::id;
use quote_security::Connection;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
pub const FORMAT: &str = "777-cluster-v1";
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Primary,
    Replica,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub format: String,
    pub cluster_id: String,
    pub ledger_id: String,
    pub node_id: String,
    pub role: Role,
    pub primary: Connection,
}
pub fn directory(root: &Path) -> PathBuf {
    root.join("private/cluster")
}
pub fn read(root: &Path) -> Result<Option<Config>> {
    let path = directory(root).join("config.json");
    if !path.try_exists()? {
        return Ok(None);
    }
    let config: Config = serde_json::from_slice(&files::read(&path, 131072)?)?;
    if config.format != FORMAT {
        return fail(409, "CLUSTER_VERSION_UNSUPPORTED");
    }
    for value in [&config.cluster_id, &config.ledger_id, &config.node_id] {
        id(value)?;
    }
    quote_security::tls::configuration(&config.primary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    Ok(Some(config))
}
pub fn required(root: &Path) -> Result<Config> {
    read(root)?.ok_or_else(|| Error::new(409, "CLUSTER_NOT_ENABLED"))
}
pub fn ensure_primary(root: &Path) -> Result<Config> {
    let c = required(root)?;
    if c.role != Role::Primary {
        return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
    }
    Ok(c)
}
pub fn connection(root: &Path) -> Result<Connection> {
    let template = files::read_json(&root.join("client-template.json"))?;
    Ok(Connection {
        url: template["url"]
            .as_str()
            .ok_or_else(|| Error::new(422, "HOST_CONFIG_INVALID"))?
            .into(),
        certificate_pem: String::from_utf8(files::read(&root.join("service-cert.pem"), 65536)?)
            .map_err(|_| Error::new(422, "INVALID_CONNECTION"))?,
        certificate_sha256: template["certificate_sha256"]
            .as_str()
            .ok_or_else(|| Error::new(422, "HOST_CONFIG_INVALID"))?
            .into(),
    })
}
pub fn save_secret(root: &Path, value: &str, auxiliary: bool) -> Result<()> {
    let bytes = quote_security::protect::protect(value.as_bytes(), true, auxiliary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    files::new_file(&directory(root).join("peer.bin"), &bytes)
}
pub fn secret(root: &Path, auxiliary: bool) -> Result<String> {
    let raw = files::read(&directory(root).join("peer.bin"), 65536)?;
    let value = quote_security::protect::protect(&raw, false, auxiliary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    String::from_utf8(value).map_err(|_| Error::new(503, "CLUSTER_CREDENTIAL_UNAVAILABLE"))
}
