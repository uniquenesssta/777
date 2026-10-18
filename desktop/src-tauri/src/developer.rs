//! Development-only, fixed loopback launcher protocol. Never compiled into deliveries.
use crate::{DesktopError, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

#[derive(Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum DeveloperAction {
    Status {},
    Select {
        root: String,
        initialize: bool,
        backup_dir: String,
        username: Option<String>,
        password: Option<String>,
    },
    ImportDirectory {
        root: String,
        target: String,
        username: String,
        password: String,
    },
    BackupDirectory {
        directory: String,
    },
    DailyBackup {
        directory: String,
        hidden: String,
        hour: u8,
    },
    RestoreData {
        package: String,
        target: String,
    },
    SavePackage {
        output: String,
        version: String,
        runtime: String,
    },
    Package {
        delivery: String,
    },
    Cancel {},
    OpenOutput {},
}
impl DeveloperAction {
    pub fn switches_data(&self) -> bool {
        matches!(
            self,
            Self::Select { .. } | Self::RestoreData { .. } | Self::ImportDirectory { .. }
        )
    }
    pub fn protects_close(&self) -> bool {
        matches!(
            self,
            Self::Select { .. }
                | Self::ImportDirectory { .. }
                | Self::BackupDirectory { .. }
                | Self::DailyBackup { .. }
                | Self::RestoreData { .. }
        )
    }
}
pub fn available() -> bool {
    std::env::var_os("QUOTE777_DEVELOPER_PORT").is_some()
}
pub async fn call(value: Value) -> Result<Value> {
    let unavailable = || DesktopError::new(503, "DEVELOPER_LAUNCHER_REQUIRED");
    let port = std::env::var("QUOTE777_DEVELOPER_PORT")
        .map_err(|_| unavailable())?
        .parse::<u16>()
        .map_err(|_| unavailable())?;
    let token = std::env::var("QUOTE777_DEVELOPER_TOKEN").map_err(|_| unavailable())?;
    if port == 0 || token.len() < 48 {
        return Err(unavailable());
    }
    let _ = rustls::crypto::ring::default_provider().install_default();
    let http = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(3))
        .timeout(Duration::from_secs(180))
        .build()
        .map_err(|_| unavailable())?;
    let mut response = http
        .post(format!("http://127.0.0.1:{port}/control"))
        .bearer_auth(token)
        .json(&value)
        .send()
        .await
        .map_err(|_| unavailable())?;
    if !response.status().is_success() {
        return Err(unavailable());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| unavailable())? {
        if bytes.len() + chunk.len() > 1024 * 1024 {
            return Err(unavailable());
        }
        bytes.extend_from_slice(&chunk);
    }
    let response: Value = serde_json::from_slice(&bytes).map_err(|_| unavailable())?;
    if let Some(code) = response["error"].as_str() {
        return Err(DesktopError::new(409, code));
    }
    response.get("value").cloned().ok_or_else(unavailable)
}
pub async fn bootstrap() -> Result<Value> {
    call(json!({"op":"bootstrap"})).await
}
