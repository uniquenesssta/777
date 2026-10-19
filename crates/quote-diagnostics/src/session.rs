//! A fresh launch folder, with a separate operation ID propagated across roots/processes.
use std::path::{Path, PathBuf};
pub fn valid_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 96
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}
fn fresh() -> String {
    let now =
        time::OffsetDateTime::now_utc().to_offset(time::UtcOffset::from_hms(8, 0, 0).unwrap());
    format!(
        "{:04}-{:02}-{:02}_{:02}{:02}{:02}_{}_{}",
        now.year(),
        now.month() as u8,
        now.day(),
        now.hour(),
        now.minute(),
        now.second(),
        std::process::id(),
        now.nanosecond()
    )
}
pub fn execution_id() -> String {
    std::env::var("QUOTE777_EXECUTION_ID")
        .ok()
        .filter(|s| valid_id(s))
        .unwrap_or_else(fresh)
}
pub(super) fn prepare() -> (PathBuf, String) {
    let root = std::env::var_os("QUOTE777_LOG_ROOT")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(Path::to_path_buf))
        })
        .unwrap_or_else(|| PathBuf::from("."));
    let session = std::env::var("QUOTE777_LOG_SESSION")
        .ok()
        .filter(|s| valid_id(s))
        .unwrap_or_else(fresh);
    let execution = std::env::var("QUOTE777_EXECUTION_ID")
        .ok()
        .filter(|s| valid_id(s))
        .unwrap_or_else(|| session.clone());
    // At process startup only, before worker threads or children are launched.
    std::env::set_var("QUOTE777_LOG_ROOT", &root);
    std::env::set_var("QUOTE777_LOG_SESSION", &session);
    std::env::set_var("QUOTE777_EXECUTION_ID", &execution);
    (root.join("logs").join(session), execution)
}

/// Read public correlation metadata only. This never changes an authorization decision.
pub fn adopt_context(path: &std::path::Path) {
    if std::env::var("QUOTE777_EXECUTION_ID")
        .ok()
        .is_some_and(|v| valid_id(&v))
    {
        return;
    }
    let value = (|| -> Option<serde_json::Value> {
        if path.metadata().ok()?.len() > 1024 {
            return None;
        }
        serde_json::from_slice(&std::fs::read(path).ok()?).ok()
    })();
    if let Some(v) = value {
        if v["format"] == "777-operation-context-v1" {
            if let Some(id) = v["execution_id"].as_str().filter(|id| valid_id(id)) {
                std::env::set_var("QUOTE777_EXECUTION_ID", id);
            }
        }
    }
}
