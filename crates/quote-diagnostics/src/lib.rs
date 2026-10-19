//! Bounded local operational logs. Callers pass metadata, never request/response bodies.
mod metadata;
mod session;
mod storage;
use serde_json::{json, Value};
pub use session::{adopt_context, execution_id, valid_id};
use std::{
    collections::HashMap,
    io,
    path::Path,
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use storage::Logger;
static LOGGER: OnceLock<Mutex<Logger>> = OnceLock::new();

pub fn enabled() -> bool {
    LOGGER.get().is_some()
}
pub fn init(component: &str) {
    if std::env::var("QUOTE777_LOG_DISABLED").as_deref() == Ok("1") {
        return;
    }
    if LOGGER.get().is_some() {
        return;
    }
    let (directory, execution_id) = session::prepare();
    let _ = LOGGER.set(Mutex::new(Logger {
        directory,
        execution_id,
        component: component.into(),
        recent: HashMap::new(),
    }));
    event(
        "runtime.start",
        json!({"version":env!("CARGO_PKG_VERSION"),"os":std::env::consts::OS,"arch":std::env::consts::ARCH,"executable":std::env::current_exe().ok(),"account":std::env::var("USERNAME").or_else(|_|std::env::var("USER")).ok()}),
    );
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        // Panic payloads may contain business data; retain only code location.
        event(
            "runtime.panic",
            json!({"location":info.location().map(|p|p.to_string())}),
        );
        previous(info);
    }));
}

pub fn event(name: &str, fields: Value) {
    record(name, fields, true);
}
/// Records each business action even if the process later exits abnormally.
/// Uses the same bounded file, rotation and write deadline as other events.
pub fn event_each(name: &str, fields: Value) {
    record(name, fields, false);
}
fn record(name: &str, fields: Value, deduplicate: bool) {
    let Some(logger) = LOGGER.get() else { return };
    let Ok(mut logger) = logger.lock() else {
        return;
    };
    let fields = metadata::safe(fields);
    let key = format!("{name}:{fields}");
    let now = Instant::now();
    if deduplicate {
        if let Some((since, count)) = logger.recent.get_mut(&key) {
            if since.elapsed() < Duration::from_secs(60) {
                *count += 1;
                return;
            }
        }
    }
    // Flush suppressed counts on the next event, including normal shutdown.
    let summaries: Vec<_> = logger
        .recent
        .iter()
        .filter(|(_, (since, count))| {
            *count > 0 && (since.elapsed() >= Duration::from_secs(60) || name == "runtime.stop")
        })
        .map(|(key, (_, count))| (key.clone(), *count))
        .collect();
    for (key, count) in summaries {
        let _ = logger.write("repeated.summary", json!({"event":key,"suppressed":count}));
        logger.recent.remove(&key);
    }
    if logger.recent.len() >= 256 {
        logger.recent.clear();
    }
    if deduplicate {
        logger.recent.insert(key, (now, 0));
    }
    if logger.write(name, fields).is_err() {
        // One warning per process; logging failure never fails a business operation.
        static WARNED: OnceLock<()> = OnceLock::new();
        if WARNED.set(()).is_ok() {
            eprintln!("LOG_WRITE_FAILED: {}", logger.directory.display());
        }
    }
}
pub fn io_error(operation: &str, path: Option<&Path>, error: &io::Error) {
    event(
        "filesystem.error",
        json!({"operation":operation,"path":path,"os_code":error.raw_os_error(),"kind":format!("{:?}",error.kind()),"message":error.to_string()}),
    );
}
pub fn io_result<T>(operation: &str, path: &Path, result: io::Result<T>) -> io::Result<T> {
    result.inspect_err(|e| io_error(operation, Some(path), e))
}

#[cfg(test)]
mod tests;
