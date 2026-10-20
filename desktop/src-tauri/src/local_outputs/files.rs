use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use sha2::{Digest, Sha256};
use std::{fs, io::Write, path::Path};
fn error() -> DesktopError {
    DesktopError::new(503, "LOCAL_OUTPUT_WRITE_FAILED")
}
pub(super) fn prepare(root: &Path) -> Result<()> {
    for p in root.ancestors().filter(|p| p.exists()) {
        crate::journal::check(p)?;
    }
    for name in ["PIC", "Excel", "内部财务报表"] {
        let dir = root.join(name);
        fs::create_dir_all(&dir).map_err(|_| error())?;
        crate::journal::check(&dir)?;
        let probe = dir.join(format!(".{}.probe", crate::types::new_id()?));
        let result = (|| {
            let mut f = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&probe)
                .map_err(|_| error())?;
            f.write_all(b"Quote")
                .and_then(|_| f.sync_all())
                .map_err(|_| error())
        })();
        let _ = fs::remove_file(probe);
        result?;
    }
    Ok(())
}
pub(crate) fn save(root: &Path, id: &str, kind: &str, content: &Value) -> Result<PathBuf> {
    crate::types::identifier(id)?;
    let (folder, extension) = folder(kind)?;
    let invalid = || DesktopError::new(502, "OUTPUT_CONTENT_INVALID");
    if content["job_id"] != id || content["format"] != "777-output-v1" {
        return Err(invalid());
    }
    let encoded = content["data_base64"].as_str().ok_or_else(invalid)?;
    if encoded.len() > 6 * 1024 * 1024 {
        return Err(invalid());
    }
    let raw = STANDARD.decode(encoded).map_err(|_| invalid())?;
    if raw.is_empty()
        || raw.len() > 4 * 1024 * 1024
        || content["size"].as_u64() != Some(raw.len() as u64)
        || content["sha256"] != format!("{:x}", Sha256::digest(&raw))
    {
        return Err(invalid());
    }
    if (extension == ".png" && !raw.starts_with(b"\x89PNG\r\n\x1a\n"))
        || (extension == ".xlsx" && !raw.starts_with(b"PK\x03\x04"))
    {
        return Err(invalid());
    }
    prepare(root)?;
    let target = root.join(folder).join(format!("Quote-{id}{extension}"));
    if target.exists() {
        crate::journal::check(&target)?;
        if fs::read(&target).map_err(|_| error())? == raw {
            return Ok(target);
        }
        return Err(DesktopError::new(409, "LOCAL_OUTPUT_FILE_CHANGED"));
    }
    let temp = target.with_extension(format!("{}.partial", crate::types::new_id()?));
    let result = (|| {
        let mut f = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp)
            .map_err(|_| error())?;
        f.write_all(&raw)
            .and_then(|_| f.sync_all())
            .map_err(|_| error())?;
        drop(f);
        // Atomic publish without overwriting an existing user's file.
        fs::hard_link(&temp, &target).map_err(|_| error())?;
        Ok(target)
    })();
    let _ = fs::remove_file(temp);
    result
}
