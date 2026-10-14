use crate::{fail, Error, Result};
use quote_ledger::{
    paths,
    store::{encoded, hash, uid},
};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::Path,
    sync::{Mutex, OnceLock},
    time::Duration,
};
pub fn local(path: &Path, exists: bool) -> Result<()> {
    Ok(paths::local(path, exists)?)
}
pub fn dir(path: &Path) -> Result<()> {
    if !fs::symlink_metadata(path)?.is_dir() {
        return fail(422, "DIRECTORY_INVALID");
    }
    local(&path.join(".777-path-check"), false)
}
pub fn new_dir(path: &Path) -> Result<()> {
    local(&path.join(".777-path-check"), false).or_else(|_| {
        local(&path.with_file_name(".777-parent-check"), false)?;
        if path.exists() {
            return fail(409, "EXISTS");
        }
        Ok(())
    })?;
    fs::create_dir(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    dir(path)
}
pub fn new_file(path: &Path, raw: &[u8]) -> Result<()> {
    local(path, false)?;
    let mut o = OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    let mut f = o.open(path)?;
    f.write_all(raw)?;
    f.sync_all()?;
    Ok(())
}
pub fn read(path: &Path, limit: usize) -> Result<Vec<u8>> {
    local(path, true)?;
    if path.metadata()?.len() > limit as u64 {
        return fail(413, "FILE_TOO_LARGE");
    }
    let raw = fs::read(path)?;
    if raw.len() > limit {
        return fail(413, "FILE_TOO_LARGE");
    }
    Ok(raw)
}
pub fn read_json(path: &Path) -> Result<Value> {
    crate::protocol::decode(&read(path, 1024 * 1024)?, 1024 * 1024)
}
pub fn replace_json(path: &Path, v: &Value) -> Result<()> {
    local(path, false)?;
    let tmp = path.with_extension(format!("{}.partial", uid()?));
    new_file(&tmp, encoded(v).as_bytes())?;
    let r = fs::rename(&tmp, path).map_err(Error::from);
    if tmp.exists() {
        let _ = fs::remove_file(&tmp);
    }
    r
}
pub fn sha(path: &Path) -> Result<String> {
    Ok(hash(read(path, 512 * 1024 * 1024)?))
}
pub fn copy(source: &Path, target: &Path) -> Result<()> {
    new_file(target, &read(source, 512 * 1024 * 1024)?)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if source.extension().is_some_and(|s| s == "exe") {
            fs::set_permissions(target, fs::Permissions::from_mode(0o700))?;
        }
    }
    Ok(())
}
pub fn database(path: &Path, application: i64, ddl: &str) -> Result<Connection> {
    local(path, true)?;
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut p = path.as_os_str().to_os_string();
        p.push(suffix);
        local(Path::new(&p), false)?;
    }
    let c = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
    c.busy_timeout(Duration::from_secs(3))?;
    c.execute_batch("PRAGMA foreign_keys=ON;PRAGMA synchronous=FULL")?;
    static EXPECTED: OnceLock<Mutex<std::collections::HashMap<i64, String>>> = OnceLock::new();
    let mut hashes = EXPECTED
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| Error::new(503, "STORE_UNAVAILABLE"))?;
    let expected = if let Some(s) = hashes.get(&application) {
        s.clone()
    } else {
        let temp = Connection::open_in_memory()?;
        temp.execute_batch(ddl)?;
        let sig = quote_ledger::store::schema_hash(&temp)?;
        hashes.insert(application, sig.clone());
        sig
    };
    drop(hashes);
    if c.query_row("PRAGMA application_id", [], |r| r.get::<_, i64>(0))? != application
        || c.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0))? != 1
        || quote_ledger::store::schema_hash(&c)? != expected
    {
        return fail(
            503,
            if application == crate::auth::APP {
                "AUTH_SCHEMA_INVALID"
            } else {
                "OUTPUT_STORE_INCOMPATIBLE"
            },
        );
    }
    Ok(c)
}
pub fn snapshot(source: &Path, target: &Path, application: i64, ddl: &str) -> Result<()> {
    new_file(target, &[])?;
    let origin = database(source, application, ddl)?;
    let mut dest = Connection::open(target)?;
    rusqlite::backup::Backup::new(&origin, &mut dest)?.run_to_completion(
        128,
        Duration::from_millis(1),
        None,
    )?;
    dest.execute_batch("PRAGMA journal_mode=DELETE")?;
    drop(dest);
    File::options().write(true).open(target)?.sync_all()?;
    Ok(())
}
pub struct Owner {
    _file: File,
}
impl Owner {
    pub fn acquire(root: &Path) -> Result<Self> {
        dir(root)?;
        let p = root.join(".service-owner.777.lock");
        local(&p, false)?;
        let f = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(p)?;
        fs2::FileExt::try_lock_exclusive(&f).map_err(|_| Error::new(409, "SERVICE_OWNER_BUSY"))?;
        Ok(Self { _file: f })
    }
}
#[cfg(not(windows))]
pub fn protect(path: &Path, auxiliary: bool) -> Result<Value> {
    dir(path)?;
    if !auxiliary {
        return fail(400, "WINDOWS_HOST_REQUIRED");
    }
    Ok(json!({"status":"auxiliary_no_native_security_claim"}))
}
#[cfg(windows)]
pub fn protect(path: &Path, auxiliary: bool) -> Result<Value> {
    use std::{ffi::c_void, os::windows::ffi::OsStrExt};
    if auxiliary {
        return fail(400, "WINDOWS_SECURITY_CANNOT_BE_DISABLED");
    }
    dir(path)?;
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetFileAttributesW(p: *const u16) -> u32;
        fn SetFileAttributesW(p: *const u16, a: u32) -> i32;
        fn GetSystemDirectoryW(p: *mut u16, n: u32) -> u32;
        fn LocalFree(p: *mut c_void) -> *mut c_void;
    }
    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
            p: *const u16,
            v: u32,
            s: *mut *mut c_void,
            n: *mut u32,
        ) -> i32;
        fn GetSecurityDescriptorDacl(
            s: *mut c_void,
            p: *mut i32,
            d: *mut *mut c_void,
            def: *mut i32,
        ) -> i32;
        fn GetAce(d: *mut c_void, index: u32, ace: *mut *mut c_void) -> i32;
        fn ConvertSidToStringSidW(sid: *const c_void, text: *mut *mut u16) -> i32;
        fn SetNamedSecurityInfoW(
            p: *mut u16,
            t: u32,
            i: u32,
            o: *mut c_void,
            g: *mut c_void,
            d: *mut c_void,
            s: *mut c_void,
        ) -> u32;
        fn GetNamedSecurityInfoW(
            p: *mut u16,
            t: u32,
            i: u32,
            o: *mut *mut c_void,
            g: *mut *mut c_void,
            d: *mut *mut c_void,
            s: *mut *mut c_void,
            sd: *mut *mut c_void,
        ) -> u32;
        fn ConvertSecurityDescriptorToStringSecurityDescriptorW(
            s: *mut c_void,
            v: u32,
            i: u32,
            p: *mut *mut u16,
            n: *mut u32,
        ) -> i32;
    }
    let mut wide = path
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let mut system = vec![0u16; 32768];
    let n = unsafe { GetSystemDirectoryW(system.as_mut_ptr(), 32768) };
    if n == 0 || n >= 32768 {
        return fail(503, "NATIVE_SECURITY_FAILED");
    }
    let output = std::process::Command::new(
        std::path::PathBuf::from(String::from_utf16_lossy(&system[..n as usize]))
            .join("whoami.exe"),
    )
    .args(["/user", "/fo", "csv", "/nh"])
    .output()?;
    if !output.status.success() {
        return fail(503, "NATIVE_SECURITY_FAILED");
    }
    let s = String::from_utf8_lossy(&output.stdout);
    let pos = s
        .find("S-1-5-")
        .ok_or_else(|| Error::new(503, "NATIVE_SECURITY_FAILED"))?;
    let sid = s[pos..]
        .chars()
        .take_while(|c| c.is_ascii_digit() || *c == 'S' || *c == '-')
        .collect::<String>();
    let mut allowed = vec![
        "S-1-5-18".to_string(),
        "S-1-5-32-544".to_string(),
        sid.clone(),
    ];
    allowed.sort();
    allowed.dedup();
    let sddl = "D:P".to_string()
        + &allowed
            .iter()
            .map(|s| format!("(A;OICI;FA;;;{s})"))
            .collect::<String>();
    let sw = sddl.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
    let mut sd = std::ptr::null_mut();
    let mut readsd = std::ptr::null_mut();
    let mut string = std::ptr::null_mut();
    let result = (|| -> Result<Value> {
        unsafe {
            let attr = GetFileAttributesW(wide.as_ptr());
            if attr == u32::MAX || SetFileAttributesW(wide.as_ptr(), attr | 6) == 0 {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            if ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sw.as_ptr(),
                1,
                &mut sd,
                std::ptr::null_mut(),
            ) == 0
            {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            let (mut present, mut defaulted, mut dacl) = (0, 0, std::ptr::null_mut());
            if GetSecurityDescriptorDacl(sd, &mut present, &mut dacl, &mut defaulted) == 0
                || present == 0
                || defaulted != 0
                || dacl.is_null()
            {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            if SetNamedSecurityInfoW(
                wide.as_mut_ptr(),
                1,
                0x80000004,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                dacl,
                std::ptr::null_mut(),
            ) != 0
            {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            if GetNamedSecurityInfoW(
                wide.as_mut_ptr(),
                1,
                4,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut readsd,
            ) != 0
                || ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    readsd,
                    1,
                    4,
                    &mut string,
                    std::ptr::null_mut(),
                ) == 0
            {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            let mut len = 0;
            while *string.add(len) != 0 {
                len += 1;
                if len > 8192 {
                    return fail(503, "NATIVE_SECURITY_FAILED");
                }
            }
            let actual = String::from_utf16_lossy(std::slice::from_raw_parts(string, len));
            // Read canonical identities from the same descriptor, rather than
            // equating display aliases such as LA with a guessed account SID.
            let (mut present, mut defaulted, mut dacl) = (0, 0, std::ptr::null_mut());
            if GetSecurityDescriptorDacl(readsd, &mut present, &mut dacl, &mut defaulted) == 0
                || present == 0
                || defaulted != 0
                || dacl.is_null()
            {
                return fail(503, "NATIVE_DACL_READBACK_FAILED");
            }
            let mut principals = Vec::new();
            for index in 0..allowed.len() {
                let mut ace = std::ptr::null_mut();
                if GetAce(dacl, index as u32, &mut ace) == 0 || ace.is_null() {
                    return fail(503, "NATIVE_DACL_READBACK_FAILED");
                }
                let bytes = ace.cast::<u8>();
                let size = u16::from_le_bytes([*bytes.add(2), *bytes.add(3)]) as usize;
                if *bytes != 0 || size < 16 {
                    return fail(503, "NATIVE_DACL_ACE_UNSUPPORTED");
                }
                if *bytes.add(8) != 1
                    || *bytes.add(9) > 15
                    || size < 16 + 4 * (*bytes.add(9) as usize)
                {
                    return fail(503, "NATIVE_DACL_SID_UNSUPPORTED");
                }
                let mut text = std::ptr::null_mut();
                let converted = (|| -> Result<String> {
                    if ConvertSidToStringSidW(bytes.add(8).cast(), &mut text) == 0 || text.is_null()
                    {
                        return fail(503, "NATIVE_DACL_SID_UNSUPPORTED");
                    }
                    let mut length = 0;
                    while *text.add(length) != 0 {
                        length += 1;
                        if length > 256 {
                            return fail(503, "NATIVE_DACL_SID_UNSUPPORTED");
                        }
                    }
                    Ok(String::from_utf16_lossy(std::slice::from_raw_parts(
                        text, length,
                    )))
                })();
                if !text.is_null() {
                    LocalFree(text.cast());
                }
                principals.push(converted?);
            }
            verify_dacl(&actual, &allowed, Some(&principals))?;
            let attributes = GetFileAttributesW(wide.as_ptr());
            if attributes == u32::MAX || attributes & 6 != 6 {
                return fail(503, "NATIVE_SECURITY_FAILED");
            }
            Ok(
                json!({"hidden":true,"system":true,"protected_dacl":true,"service_identity_sid":sid,"allowed_sids":allowed}),
            )
        }
    })();
    unsafe {
        if !string.is_null() {
            LocalFree(string.cast());
        }
        if !readsd.is_null() {
            LocalFree(readsd);
        }
        if !sd.is_null() {
            LocalFree(sd);
        }
    }
    result
}
pub struct Lock {
    _file: File,
}
impl Lock {
    pub fn acquire(path: &Path) -> Result<Self> {
        let name = path
            .file_name()
            .ok_or_else(|| Error::new(422, "PATH_INVALID"))?
            .to_string_lossy();
        let p = path.with_file_name(format!(".{name}.777.lock"));
        local(&p, false)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(p)?;
        fs2::FileExt::try_lock_exclusive(&file).map_err(|_| Error::new(409, "FILE_BUSY"))?;
        Ok(Self { _file: file })
    }
}
/// Exclusive atomic publication. Rust fs::rename replaces on Windows too;
/// MoveFileEx without REPLACE_EXISTING matches the frozen Python protocol.
pub fn publish_new(source: &Path, target: &Path) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn MoveFileExW(source: *const u16, target: *const u16, flags: u32) -> i32;
        }
        let from = source
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect::<Vec<_>>();
        let to = target
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect::<Vec<_>>();
        if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), 8) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        fs::hard_link(source, target)
    }
}
pub fn verify_dacl(value: &str, allowed: &[String], principals: Option<&[String]>) -> Result<()> {
    let rest = value
        .strip_prefix("D:")
        .ok_or_else(|| Error::new(503, "NATIVE_SECURITY_FAILED"))?;
    let pos = rest
        .find('(')
        .ok_or_else(|| Error::new(503, "NATIVE_SECURITY_FAILED"))?;
    let mut flags = &rest[..pos];
    let mut protected = false;
    while !flags.is_empty() {
        if let Some(f) = flags.strip_prefix('P') {
            protected = true;
            flags = f;
        } else if let Some(f) = flags
            .strip_prefix("AI")
            .or_else(|| flags.strip_prefix("AR"))
        {
            flags = f;
        } else {
            return fail(503, "NATIVE_SECURITY_FAILED");
        }
    }
    if !protected {
        return fail(503, "NATIVE_SECURITY_FAILED");
    }
    let entries = rest[pos..].split_inclusive(')').collect::<Vec<_>>();
    if entries.len() != allowed.len() {
        return fail(503, "NATIVE_SECURITY_FAILED");
    }
    if principals.is_some_and(|s| s.len() != entries.len()) {
        return fail(503, "NATIVE_DACL_PRINCIPAL_COUNT_MISMATCH");
    }
    let mut seen = std::collections::BTreeSet::new();
    for (index, entry) in entries.into_iter().enumerate() {
        let entry = entry
            .strip_prefix('(')
            .and_then(|e| e.strip_suffix(')'))
            .ok_or_else(|| Error::new(503, "NATIVE_SECURITY_FAILED"))?;
        let parts = entry.split(';').collect::<Vec<_>>();
        if parts.len() != 6
            || parts[0] != "A"
            || !["OICI", "CIOI"].contains(&parts[1])
            || !["fa", "0x1f01ff", "0x001f01ff"].contains(&parts[2].to_lowercase().as_str())
            || !parts[3].is_empty()
            || !parts[4].is_empty()
        {
            return fail(503, "NATIVE_SECURITY_FAILED");
        }
        let sid = match principals {
            Some(sids) => sids[index].as_str(),
            None => match parts[5] {
                "SY" => "S-1-5-18",
                "BA" => "S-1-5-32-544",
                s => s,
            },
        };
        if !allowed.iter().any(|s| s == sid) || !seen.insert(sid) {
            return fail(503, "NATIVE_DACL_PRINCIPAL_MISMATCH");
        }
    }
    Ok(())
}
