//! Verify the installed worker can read schema 3 before touching the live ledger.
use super::*;
struct Probe(PathBuf);
impl Drop for Probe {
    fn drop(&mut self) {
        for suffix in ["", "-wal", "-shm"] {
            let mut path = self.0.as_os_str().to_os_string();
            path.push(suffix);
            let _ = std::fs::remove_file(PathBuf::from(path));
        }
    }
}
pub(super) fn check(s: &Service) -> Result<()> {
    if s.config.get("rust_worker_sha256").is_none() {
        return Ok(());
    }
    let path = s
        .root
        .join("private")
        .join(format!(".offline-probe-{}.sqlite3", store::uid()?));
    let _owned = Probe(path.clone());
    store::create(&path)?;
    let mut c = store::open(&path, true)?;
    quote_ledger::intake::upgrade(&mut c)?;
    drop(c);
    let expected = quote_ledger::integrity::inventory(&store::open(&path, false)?)?;
    let actual = crate::host::probe_worker(
        &s.root.join("private/rust-ledger-worker.exe"),
        &path,
        s.auxiliary,
    )?;
    if actual != expected {
        return Err(Error::new(503, "WORKER_RESOURCE_INCOMPATIBLE"));
    }
    Ok(())
}
