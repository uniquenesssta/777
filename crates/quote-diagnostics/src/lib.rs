//! Bounded local operational logs. Callers pass metadata, never request/response bodies.
use fs2::FileExt;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
const LIMIT: u64 = 4 * 1024 * 1024;
const COPIES: usize = 4;
struct Logger {
    directory: PathBuf,
    component: String,
    recent: HashMap<String, (Instant, u64)>,
}
static LOGGER: OnceLock<Mutex<Logger>> = OnceLock::new();

pub fn init(component: &str) {
    let directory = std::env::var_os("QUOTE777_LOG_ROOT")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(Path::to_path_buf))
        })
        .unwrap_or_else(|| PathBuf::from("."))
        .join("logs");
    let _ = LOGGER.set(Mutex::new(Logger {
        directory,
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
    let Some(logger) = LOGGER.get() else { return };
    let Ok(mut logger) = logger.lock() else {
        return;
    };
    let key = format!("{name}:{fields}");
    let now = Instant::now();
    if let Some((since, count)) = logger.recent.get_mut(&key) {
        if since.elapsed() < Duration::from_secs(60) {
            *count += 1;
            return;
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
    logger.recent.insert(key, (now, 0));
    if logger.write(name, fields).is_err() {
        // One warning per process; logging failure never fails a business operation.
        static WARNED: OnceLock<()> = OnceLock::new();
        if WARNED.set(()).is_ok() {
            eprintln!("LOG_WRITE_FAILED: {}", logger.directory.display());
        }
    }
}
impl Logger {
    fn write(&self, name: &str, fields: Value) -> io::Result<()> {
        fs::create_dir_all(&self.directory)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(self.directory.join(format!("{}.lock", self.component)))?;
        // Do not wait for another process holding the rotation lock.
        lock.try_lock_exclusive()?;
        let path = self.directory.join(format!("{}.jsonl", self.component));
        let line = serde_json::to_vec(
            &json!({"time_unix_ms":SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis(),"pid":std::process::id(),"component":self.component,"event":name,"fields":fields}),
        )?;
        if line.len() > 16384 {
            return Ok(());
        }
        if path.metadata().map(|m| m.len()).unwrap_or(0) + line.len() as u64 + 1 > LIMIT {
            let old = self
                .directory
                .join(format!("{}.{}.jsonl", self.component, COPIES));
            if old.exists() {
                fs::remove_file(old)?;
            }
            for i in (1..COPIES).rev() {
                let from = self
                    .directory
                    .join(format!("{}.{}.jsonl", self.component, i));
                if from.exists() {
                    fs::rename(
                        from,
                        self.directory
                            .join(format!("{}.{}.jsonl", self.component, i + 1)),
                    )?;
                }
            }
            if path.exists() {
                fs::rename(
                    &path,
                    self.directory.join(format!("{}.1.jsonl", self.component)),
                )?;
            }
        }
        let mut file = OpenOptions::new().create(true).append(true).open(path)?;
        file.write_all(&line)?;
        file.write_all(b"\n")?;
        Ok(())
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
mod tests {
    use super::*;
    #[test]
    fn repeated_events_are_counted_without_flooding() {
        let directory = std::env::temp_dir().join(format!("777-log-flood-{}", std::process::id()));
        let _ = LOGGER.set(Mutex::new(Logger {
            directory: directory.clone(),
            component: "test".into(),
            recent: HashMap::new(),
        }));
        for _ in 0..10000 {
            event("failure", json!({"code":"PATH_UNAVAILABLE"}));
        }
        event("runtime.stop", json!({}));
        let raw = fs::read_to_string(directory.join("test.jsonl")).unwrap();
        let rows: Vec<Value> = raw
            .lines()
            .map(|v| serde_json::from_str(v).unwrap())
            .collect();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[1]["fields"]["suppressed"], 9999);
        fs::remove_dir_all(directory).unwrap();
    }
    #[test]
    fn rotates_only_owned_logs_and_preserves_json() {
        let directory = std::env::temp_dir().join(format!("777-log-test-{}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        fs::write(directory.join("unrelated.txt"), b"keep").unwrap();
        let logger = Logger {
            directory: directory.clone(),
            component: "test".into(),
            recent: HashMap::new(),
        };
        for _ in 0..6 {
            fs::write(directory.join("test.jsonl"), vec![b' '; LIMIT as usize]).unwrap();
            logger
                .write("test.error", json!({"path":"\\\\server\\共享","os_code":5}))
                .unwrap();
        }
        assert!(directory.join("test.4.jsonl").exists());
        assert!(!directory.join("test.5.jsonl").exists());
        assert_eq!(fs::read(directory.join("unrelated.txt")).unwrap(), b"keep");
        let record: Value =
            serde_json::from_slice(&fs::read(directory.join("test.jsonl")).unwrap()).unwrap();
        assert_eq!(record["fields"]["os_code"], 5);
        fs::remove_dir_all(directory).unwrap();
    }
}
