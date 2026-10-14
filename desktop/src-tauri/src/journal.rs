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
        fs::create_dir_all(&root).map_err(|_| error())?;
        check(&root)?;
        Ok(Self { root, auxiliary })
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
    Ok(())
}
fn protect(data: &[u8], encrypt: bool, auxiliary: bool) -> Result<Vec<u8>> {
    #[cfg(not(windows))]
    {
        let _ = encrypt;
        if auxiliary {
            return Ok(data.to_vec());
        }
        Err(error())
    }
    #[cfg(windows)]
    {
        let _ = auxiliary;
        use std::ffi::c_void;
        #[repr(C)]
        struct Blob {
            size: u32,
            data: *mut u8,
        }
        #[link(name = "crypt32")]
        unsafe extern "system" {
            fn CryptProtectData(
                a: *const Blob,
                b: *const u16,
                c: *const Blob,
                d: *mut c_void,
                e: *mut c_void,
                f: u32,
                g: *mut Blob,
            ) -> i32;
            fn CryptUnprotectData(
                a: *const Blob,
                b: *mut *mut u16,
                c: *const Blob,
                d: *mut c_void,
                e: *mut c_void,
                f: u32,
                g: *mut Blob,
            ) -> i32;
        }
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn LocalFree(p: *mut c_void) -> *mut c_void;
        }
        let input = Blob {
            size: data.len() as u32,
            data: data.as_ptr() as *mut u8,
        };
        let mut out = Blob {
            size: 0,
            data: std::ptr::null_mut(),
        };
        unsafe {
            let ok = if encrypt {
                CryptProtectData(
                    &input,
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    1,
                    &mut out,
                )
            } else {
                CryptUnprotectData(
                    &input,
                    std::ptr::null_mut(),
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    1,
                    &mut out,
                )
            };
            if ok == 0 {
                if !out.data.is_null() {
                    LocalFree(out.data.cast());
                }
                return Err(error());
            }
            let value = std::slice::from_raw_parts(out.data, out.size as usize).to_vec();
            LocalFree(out.data.cast());
            Ok(value)
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
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
