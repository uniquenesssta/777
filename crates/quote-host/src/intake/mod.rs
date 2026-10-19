//! Receive-only foundation; business application and client offline mode follow separately.
pub mod api;
mod capacity;
mod context;
pub mod envelope;
mod leases;
mod payload;
mod progress;
mod resources;
pub mod setup;
mod storage;
use crate::{auth::Auth, files, service::Service, Error, Result};
use quote_ledger::store;
use ring::signature::{Ed25519KeyPair, KeyPair};
use serde_json::Value;
use std::{path::PathBuf, sync::Mutex};
pub const FORMAT: &str = "777-offline-order-v1";
pub const LEASE: &str = "777-offline-lease-v1";
pub struct Intake {
    root: PathBuf,
    ledger: PathBuf,
    auth: Auth,
    outputs: Option<crate::outputs::Outputs>,
    config: Value,
    key: Ed25519KeyPair,
    capacity: Mutex<capacity::Capacity>,
    test_fault: Option<PathBuf>,
}
impl Intake {
    pub fn open(s: &Service) -> Result<Option<Self>> {
        let private = s.root.join("private");
        let path = private.join("offline-intake.json");
        if !path.try_exists()? {
            return Ok(None);
        }
        setup::require_local(&s.ledger)?;
        let config = files::read_json(&path)?;
        if config["format"] != FORMAT
            || config["mode"] != "receive_only"
            || config["ledger_id"] != s.config["ledger_id"]
            || store::verify(&store::open(&s.ledger, false)?)?["schema_version"] != 3
        {
            return Err(Error::new(503, "OFFLINE_INTAKE_CONFIGURATION_INVALID"));
        }
        let key =
            Ed25519KeyPair::from_pkcs8(&files::read(&private.join("offline-signing.pk8"), 4096)?)
                .map_err(|_| Error::new(503, "OFFLINE_SIGNING_KEY_INVALID"))?;
        if config["key_id"] != store::hash(key.public_key().as_ref()) {
            return Err(Error::new(503, "OFFLINE_SIGNING_KEY_INVALID"));
        }
        let c = store::open(&s.ledger, false)?;
        let epoch: String = c.query_row("SELECT epoch FROM offline_meta WHERE id=1", [], |r| {
            r.get(0)
        })?;
        if config["epoch"] != epoch {
            return Err(Error::new(503, "OFFLINE_INTAKE_EPOCH_CONFLICT"));
        }
        Ok(Some(Self {
            root: s.root.clone(),
            ledger: s.ledger.clone(),
            auth: Auth::open(s.auth.path.clone())?,
            outputs: s
                .outputs
                .as_ref()
                .map(|o| {
                    crate::outputs::Outputs::open(
                        o.path.clone(),
                        s.config["ledger_id"].as_str().unwrap(),
                    )
                })
                .transpose()?,
            config,
            key,
            capacity: Mutex::new(capacity::Capacity::default()),
            test_fault: s.test_fault.clone(),
        }))
    }
    pub fn handle(&self, method: &str, path: &str, token: &str, data: &Value) -> Result<Value> {
        api::handle(self, method, path, token, data)
    }
    pub fn advance(&self, cursor: &mut String) -> Result<bool> {
        progress::scan(self, cursor)
    }
}
fn fault(i: &Intake, phase: &str) {
    if i.test_fault
        .as_ref()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .is_some_and(|s| s == phase)
    {
        std::process::exit(if phase == "intake_after_commit" {
            18
        } else {
            17
        });
    }
}
