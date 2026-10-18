use crate::{DesktopError, Result};
use serde::{de::DeserializeOwned, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
const LIMIT: usize = 2 * 1024 * 1024;
pub struct Store {
    root: PathBuf,
    auxiliary: bool,
}
fn error() -> DesktopError {
    DesktopError::new(503, "LOCAL_PENDING_UNAVAILABLE")
}
impl Store {
    pub fn new(root: PathBuf, auxiliary: bool) -> Result<Self> {
        if cfg!(windows) == auxiliary {
            return Err(DesktopError::new(422, "ACTUAL_WINDOWS_REQUIRED"));
        }
        for p in root.ancestors().filter(|p| p.exists()) {
            check(p)?;
        }
        fs::create_dir_all(&root).map_err(|_| error())?;
        check(&root)?;
        Ok(Self { root, auxiliary })
    }
    pub fn profile(&self) -> String {
        self.root.to_string_lossy().into_owned()
    }
    pub fn bootstrap<T: DeserializeOwned>(&self) -> Result<Option<T>> {
        check(&self.root)?;
        let p = self.root.join("bootstrap.json");
        if !p.try_exists().map_err(|_| error())? {
            return Ok(None);
        }
        check(&p)?;
        if fs::metadata(&p).map_err(|_| error())?.len() > 65536 {
            return Err(error());
        }
        Ok(Some(
            serde_json::from_slice(&fs::read(p).map_err(|_| error())?).map_err(|_| error())?,
        ))
    }
    pub fn read<T: DeserializeOwned>(&self, name: &str) -> Result<Option<T>> {
        check(&self.root)?;
        let p = self.root.join(name);
        if !p.try_exists().map_err(|_| error())? {
            return Ok(None);
        }
        check(&p)?;
        let m = fs::metadata(&p).map_err(|_| error())?;
        if m.len() > LIMIT as u64 {
            return Err(error());
        }
        let data = fs::read(p).map_err(|_| error())?;
        let decoded = protect(&data, false, self.auxiliary)?;
        Ok(Some(serde_json::from_slice(&decoded).map_err(|_| error())?))
    }
    pub fn write<T: Serialize>(&self, name: &str, value: &T) -> Result<()> {
        check(&self.root)?;
        let p = self.root.join(name);
        let raw = serde_json::to_vec(value).map_err(|_| error())?;
        if raw.len() > LIMIT {
            return Err(error());
        }
        let data = protect(&raw, true, self.auxiliary)?;
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&p)
            .map_err(|_| error())?;
        if f.write_all(&data).and_then(|_| f.sync_all()).is_err() {
            drop(f);
            let _ = fs::remove_file(p);
            return Err(error());
        }
        Ok(())
    }
    pub fn clear(&self, name: &str) -> Result<()> {
        check(&self.root)?;
        let p = self.root.join(name);
        if p.try_exists().map_err(|_| error())? {
            check(&p)?;
            fs::remove_file(p).map_err(|_| error())?;
        }
        Ok(())
    }
}
fn check(p: &Path) -> Result<()> {
    for p in p.ancestors() {
        let m = fs::symlink_metadata(p).map_err(|_| error())?;
        if m.file_type().is_symlink() {
            return Err(error());
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if m.file_attributes() & 0x400 != 0 {
                return Err(error());
            }
        }
    }
    Ok(())
}
fn protect(data: &[u8], encrypt: bool, auxiliary: bool) -> Result<Vec<u8>> {
    quote_security::protect::protect(data, encrypt, auxiliary).map_err(|_| error())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ancestor_links_are_rejected_before_creating_profile_or_writing() {
        let p = std::env::temp_dir().join(format!(
            "777-desktop-path-{}",
            crate::types::new_id().unwrap()
        ));
        fs::create_dir(&p).unwrap();
        fs::create_dir(p.join("real")).unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink(p.join("real"), p.join("alias")).unwrap();
        #[cfg(windows)]
        {
            let status = std::process::Command::new("cmd")
                .args(["/d", "/c", "mklink", "/J"])
                .arg(p.join("alias"))
                .arg(p.join("real"))
                .output()
                .unwrap();
            assert!(status.status.success());
        }
        assert!(Store::new(p.join("alias/new-profile"), !cfg!(windows)).is_err());
        assert!(!p.join("real/new-profile").exists());
        #[cfg(windows)]
        fs::remove_dir(p.join("alias")).unwrap();
        #[cfg(unix)]
        fs::remove_file(p.join("alias")).unwrap();
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn pending_is_exclusive_and_corruption_is_never_silently_discarded() {
        let p = std::env::temp_dir().join(format!(
            "777-desktop-journal-{}",
            crate::types::new_id().unwrap()
        ));
        let s = Store::new(p.clone(), !cfg!(windows)).unwrap();
        s.write(
            "pending",
            &serde_json::json!({"token":"not-a-session","id":"00003"}),
        )
        .unwrap();
        assert!(s.write("pending", &1).is_err());
        assert_eq!(
            s.read::<serde_json::Value>("pending").unwrap().unwrap()["id"],
            "00003"
        );
        #[cfg(windows)]
        assert!(!fs::read(p.join("pending"))
            .unwrap()
            .windows(5)
            .any(|w| w == b"00003"));
        fs::write(p.join("pending"), b"corrupt").unwrap();
        assert!(s.read::<serde_json::Value>("pending").is_err());
        s.clear("pending").unwrap();
        fs::remove_dir_all(p).unwrap();
    }
}
