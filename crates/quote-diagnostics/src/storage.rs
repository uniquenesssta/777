//! Shared cross-process append/rotation lock. Only owned runtime files rotate.
use fs2::FileExt;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    io::{self, Write},
    path::PathBuf,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
pub(super) const LIMIT: u64 = 4 * 1024 * 1024;
const COPIES: usize = 2;
pub(super) struct Logger {
    pub directory: PathBuf,
    pub component: String,
    pub execution_id: String,
    pub recent: HashMap<String, (Instant, u64)>,
}
impl Logger {
    pub(super) fn write(&self, name: &str, fields: Value) -> io::Result<()> {
        fs::create_dir_all(&self.directory)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(self.directory.join("runtime.lock"))?;
        // The same lock covers append and rotation in Rust and Python.
        let deadline = Instant::now() + Duration::from_millis(100);
        loop {
            match lock.try_lock_exclusive() {
                Ok(()) => break,
                Err(e) if e.kind() == io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(2))
                }
                Err(e) => return Err(e),
            }
        }
        let path = self.directory.join("runtime.jsonl");
        let line = serde_json::to_vec(
            &json!({"time_unix_ms":SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis(),"pid":std::process::id(),"component":self.component,"execution_id":self.execution_id,"session":self.directory.file_name().map(|s|s.to_string_lossy()),"event":name,"fields":fields}),
        )?;
        if line.len() > 16384 {
            return Ok(());
        }
        if path.metadata().map(|m| m.len()).unwrap_or(0) + line.len() as u64 + 1 > LIMIT {
            let old = self.directory.join(format!("runtime.{COPIES}.jsonl"));
            if old.exists() {
                fs::remove_file(old)?;
            }
            for i in (1..COPIES).rev() {
                let from = self.directory.join(format!("runtime.{i}.jsonl"));
                if from.exists() {
                    fs::rename(
                        from,
                        self.directory.join(format!("runtime.{}.jsonl", i + 1)),
                    )?;
                }
            }
            if path.exists() {
                fs::rename(&path, self.directory.join("runtime.1.jsonl"))?;
            }
        }
        let mut file = OpenOptions::new().create(true).append(true).open(path)?;
        file.write_all(&line)?;
        file.write_all(b"\n")?;
        Ok(())
    }
}
