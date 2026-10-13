use crate::{Error, Result};
use std::{
    fs,
    path::{Component, Path},
};
pub fn local(path: &Path, exists: bool) -> Result<()> {
    if !path.is_absolute()
        || (path.to_string_lossy().starts_with("\\\\") || path.to_string_lossy().starts_with("//"))
        || path.components().any(|c| matches!(c, Component::ParentDir))
    {
        return Err(Error::new("LOCAL_PATH_REQUIRED"));
    }
    #[cfg(windows)]
    {
        use std::os::windows::{ffi::OsStrExt, fs::MetadataExt};
        use std::path::Prefix;
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetDriveTypeW(root: *const u16) -> u32;
        }
        let Some(Component::Prefix(prefix)) = path.components().next() else {
            return Err(Error::new("LOCAL_PATH_REQUIRED"));
        };
        let Prefix::Disk(drive) = prefix.kind() else {
            return Err(Error::new("LOCAL_PATH_REQUIRED"));
        };
        let anchor = format!("{}:\\", drive as char);
        let root: Vec<u16> = std::ffi::OsStr::new(&anchor)
            .encode_wide()
            .chain(Some(0))
            .collect();
        if unsafe { GetDriveTypeW(root.as_ptr()) } != 3 {
            return Err(Error::new("FIXED_DISK_REQUIRED"));
        }
        for p in path.ancestors() {
            match fs::symlink_metadata(p) {
                Ok(m) if m.file_attributes() & 0x400 != 0 => {
                    return Err(Error::new("LINK_DISALLOWED"))
                }
                Ok(_) => (),
                Err(e) if p == path && !exists && e.kind() == std::io::ErrorKind::NotFound => (),
                Err(_) => return Err(Error::new("LOCAL_PATH_UNAVAILABLE")),
            }
        }
    }
    for p in path.ancestors() {
        match fs::symlink_metadata(p) {
            Ok(m) => {
                if m.file_type().is_symlink()
                    || p == path && !m.is_file()
                    || p != path && !m.is_dir()
                {
                    return Err(Error::new("LINK_OR_TYPE_DISALLOWED"));
                }
            }
            Err(e) if p == path && !exists && e.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => return Err(Error::new("LOCAL_PATH_UNAVAILABLE")),
        }
    }
    Ok(())
}
pub fn sidecars(path: &Path) -> Result<()> {
    for suffix in ["-wal", "-shm"] {
        let mut name = path.as_os_str().to_os_string();
        name.push(suffix);
        local(Path::new(&name), false)?;
    }
    Ok(())
}
