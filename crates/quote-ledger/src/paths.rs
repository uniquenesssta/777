use crate::{Error, Result};
use std::{
    fs,
    path::{Component, Path},
};

/// Filesystem paths may use local, removable, mapped or UNC storage.
/// Directory aliases are resolved by the OS; managed files must remain regular files.
pub fn absolute(path: &Path) -> bool {
    if !path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
        return false;
    }
    #[cfg(windows)]
    {
        use std::path::Prefix;
        matches!(path.components().next(), Some(Component::Prefix(p)) if matches!(p.kind(),
            Prefix::Disk(_) | Prefix::UNC(_, _) | Prefix::VerbatimDisk(_) | Prefix::VerbatimUNC(_, _)))
    }
    #[cfg(not(windows))]
    {
        true
    }
}
pub fn local(path: &Path, exists: bool) -> Result<()> {
    if !absolute(path) {
        return Err(Error::new("FILESYSTEM_PATH_REQUIRED"));
    }
    for p in path.ancestors() {
        let metadata = if p == path {
            fs::symlink_metadata(p)
        } else {
            fs::metadata(p)
        };
        if let Err(ref error) = metadata {
            if !(p == path && !exists && error.kind() == std::io::ErrorKind::NotFound) {
                quote_diagnostics::io_error("path.metadata", Some(p), error);
            }
        }
        match metadata {
            Ok(m) => {
                if p == path && (!m.is_file() || m.file_type().is_symlink())
                    || p != path && !m.is_dir()
                {
                    return Err(Error::new("LINK_OR_TYPE_DISALLOWED"));
                }
            }
            Err(e) if p == path && !exists && e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                return Err(Error::new("PATH_PERMISSION_DENIED"))
            }
            Err(_) => return Err(Error::new("PATH_UNAVAILABLE")),
        }
    }
    Ok(())
}
/// Never use WAL/shared memory on network storage. Resolve directory aliases first.
pub fn journal_mode(path: &Path) -> &'static str {
    #[cfg(windows)]
    {
        use std::{os::windows::ffi::OsStrExt, path::Prefix};
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetDriveTypeW(root: *const u16) -> u32;
        }
        let parent = path.parent().and_then(|p| p.canonicalize().ok());
        let Some(Component::Prefix(p)) = parent.as_deref().and_then(|p| p.components().next())
        else {
            return "DELETE";
        };
        let (Prefix::Disk(d) | Prefix::VerbatimDisk(d)) = p.kind() else {
            return "DELETE";
        };
        let anchor = format!("{}:\\", d as char);
        let wide: Vec<u16> = std::ffi::OsStr::new(&anchor)
            .encode_wide()
            .chain(Some(0))
            .collect();
        if unsafe { GetDriveTypeW(wide.as_ptr()) } == 3 {
            return "WAL";
        }
        "DELETE"
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        "WAL"
    }
}
pub fn sidecars(path: &Path) -> Result<()> {
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut name = path.as_os_str().to_os_string();
        name.push(suffix);
        local(Path::new(&name), false)?;
    }
    Ok(())
}
