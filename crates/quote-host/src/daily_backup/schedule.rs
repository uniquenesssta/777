//! Short, silent destination probes; immutable snapshots are retried from disk.
use super::{business_day, cache_root, config, create_date, status};
use crate::{service::Service, Result};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};

pub const CHECK_INTERVAL: Duration = Duration::from_secs(2);

/// Prepare using local state while locked, then probe SMB after releasing the
/// service mutex. A disconnected backup share must not hold the business lock.
pub struct Check {
    due: bool,
    paths: BTreeSet<PathBuf>,
}
impl Check {
    pub fn ready(self) -> bool {
        self.due || self.paths.iter().any(|path| fs::File::open(path).is_ok())
    }
}
pub fn check(s: &Service) -> Result<Check> {
    let cfg = config(s)?;
    let clock = time::OffsetDateTime::now_utc();
    let current = business_day(clock);
    let state = status(s)?;
    let mut result = Check {
        due: false,
        paths: BTreeSet::new(),
    };
    let entry = &state["entries"][&current];
    result.due = entry.is_null()
        && u64::from(
            clock
                .to_offset(time::UtcOffset::from_hms(8, 0, 0).unwrap())
                .hour(),
        ) >= cfg["daily_hour"].as_u64().unwrap();
    if let Some(entries) = state["entries"].as_object() {
        for (date, entry) in entries {
            if date != &current && !cache_root(s).join(date).exists() {
                continue;
            }
            if complete(entry, &s.config["backup_dir"], &cfg["hidden_dir"]) {
                if date != &current && cache_root(s).join(date).exists() {
                    result.due = true;
                }
                continue;
            }
            for (label, target, marker) in destinations(s, &cfg) {
                if let Some(path) = target.as_str().filter(|p| !p.is_empty()) {
                    if !delivered(entry, label, target) {
                        result.paths.insert(Path::new(path).join(marker));
                    }
                }
            }
        }
    }
    Ok(result)
}

pub(super) fn delivered(entry: &Value, label: &str, target: &Value) -> bool {
    entry[label]["ok"] == true && entry[label]["target"] == *target
}
fn complete(entry: &Value, normal: &Value, hidden: &Value) -> bool {
    delivered(entry, "normal", normal) && (hidden == "" || delivered(entry, "hidden", hidden))
}
fn destinations<'a>(
    s: &'a Service,
    cfg: &'a Value,
) -> [(&'static str, &'a Value, &'static str); 2] {
    [
        ("normal", &s.config["backup_dir"], "777-backups.json"),
        ("hidden", &cfg["hidden_dir"], "777-hidden-data.json"),
    ]
}
fn retry_ready(s: &Service, entry: &Value, cfg: &Value) -> bool {
    destinations(s, cfg)
        .into_iter()
        .any(|(label, target, marker)| {
            let Some(path) = target.as_str().filter(|p| !p.is_empty()) else {
                return false;
            };
            // Probe only pending destinations. Do not read snapshot/Excel, create files,
            // or log repeated network misses. Delivery still validates store identity.
            !delivered(entry, label, target) && fs::File::open(Path::new(path).join(marker)).is_ok()
        })
}
pub fn due(s: &Service) -> Result<Option<Value>> {
    due_at(s, time::OffsetDateTime::now_utc())
}
pub(super) fn due_at(s: &Service, clock: time::OffsetDateTime) -> Result<Option<Value>> {
    let cfg = config(s)?;
    let current = business_day(clock);
    let state = status(s)?;
    let mut retried = None;
    // A restart reloads this same durable queue. Never fabricate historical days.
    if let Some(entries) = state["entries"].as_object() {
        for (date, entry) in entries {
            if date == &current {
                continue;
            }
            let cache = cache_root(s).join(date);
            if complete(entry, &s.config["backup_dir"], &cfg["hidden_dir"]) {
                if cache.exists() {
                    fs::remove_dir_all(cache)?;
                }
            } else if cache.exists() && retry_ready(s, entry, &cfg) {
                if let Ok(value) = create_date(s, date, &current, true) {
                    retried = Some(value);
                }
            }
        }
    }
    let now = clock.to_offset(time::UtcOffset::from_hms(8, 0, 0).unwrap());
    let entry = &state["entries"][&current];
    if (entry.is_null() && u64::from(now.hour()) < cfg["daily_hour"].as_u64().unwrap())
        || complete(entry, &s.config["backup_dir"], &cfg["hidden_dir"])
        || (!entry.is_null() && !retry_ready(s, entry, &cfg))
    {
        return Ok(retried);
    }
    create_date(s, &current, &current, true).map(Some)
}
