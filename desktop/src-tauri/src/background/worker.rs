//! A single native worker outlives the WebView and retains resumable business state.
use super::*;
pub fn run() -> Result<()> {
    if !crate::startup::formal() {
        return Err(failure());
    }
    let root = root()?;
    let store = crate::journal::Store::new(root.clone(), false)?;
    let (business, _) = store.local_database()?;
    let lock = business.with_file_name("offline-worker.sqlite3");
    if lock.exists() {
        let m = std::fs::symlink_metadata(&lock).map_err(|_| failure())?;
        use std::os::windows::fs::MetadataExt;
        if m.file_attributes() & 0x400 != 0 {
            return Err(failure());
        }
    }
    let owner = rusqlite::Connection::open(&lock).map_err(|_| failure())?;
    // SQLite's OS lock is released on crash/logoff. An old file cannot prevent restart.
    owner
        .busy_timeout(std::time::Duration::from_secs(30))
        .map_err(|_| failure())?;
    if owner.execute_batch("BEGIN EXCLUSIVE").is_err() {
        return Ok(());
    }
    let package_file = root.join("automatic-package.bin");
    let installed = std::fs::metadata(&package_file)
        .and_then(|m| m.modified())
        .map_err(|_| failure())?;
    let mut desktop = Desktop::new(root, false)?;
    desktop.load_background_package()?;
    let runtime = tokio::runtime::Runtime::new().map_err(|_| failure())?;
    runtime.block_on(async move {
        loop {
            if std::fs::metadata(&package_file)
                .and_then(|m| m.modified())
                .ok()
                != Some(installed)
            {
                return Ok(());
            }
            let _ = desktop.sync_tick().await;
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }
    })
}
