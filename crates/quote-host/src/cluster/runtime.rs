//! Snapshot scheduling and bounded state transitions, separate from the HTTPS host.
use super::{config::Config, replica, snapshot};
use crate::{service::Service, Error};
use serde_json::Value;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
pub fn changes(method: &str, path: &str, body: &Value) -> bool {
    if method != "POST" {
        return false;
    }
    if path == "/v1/cluster/forward" {
        return changes(
            body["method"].as_str().unwrap_or(""),
            body["path"].as_str().unwrap_or(""),
            &Value::Null,
        );
    }
    !path.starts_with("/v1/cluster/")
        && ![
            "/v1/calculate",
            "/v1/order-preview",
            "/v1/customer-orders",
            "/v1/developer/orders/list",
        ]
        .contains(&path)
}
pub fn source(
    service: Arc<Mutex<Service>>,
    config: Config,
    root: PathBuf,
    stop: Arc<AtomicBool>,
    dirty: Arc<AtomicBool>,
) {
    while !stop.load(Ordering::SeqCst) {
        if dirty.swap(false, Ordering::SeqCst) {
            let outcome = service
                .lock()
                .map_err(|_| Error::new(503, "SERVICE_UNAVAILABLE"))
                .and_then(|s| snapshot::capture(&s, &config));
            let generation = snapshot::current(&root)
                .ok()
                .flatten()
                .map(|p| p.generation)
                .unwrap_or(0);
            if let Err(error) = outcome {
                dirty.store(true, Ordering::SeqCst);
                let _ = replica::status(&root, "snapshot_failed", generation, Some(&error.code));
            } else {
                let _ = replica::status(&root, "primary", generation, None);
            }
        }
        for _ in 0..20 {
            if stop.load(Ordering::SeqCst) {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
}
