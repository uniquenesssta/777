//! Directory-only browsing runs on the Host under its Windows service account.
use super::*;
use std::path::PathBuf;

pub(super) fn validate(s: &Service, path: &Path) -> Result<()> {
    files::dir(path)?; // Selection must exist; never create arbitrary server paths through this API.
    let canonical = path.canonicalize()?;
    let root = s.root.canonicalize()?;
    let hidden = daily_backup::config(s)?;
    if canonical.starts_with(&root) || root.starts_with(&canonical) {
        return fail(422, "BACKUP_DIRECTORY_CONFLICT");
    }
    if let Some(h) = hidden["hidden_dir"].as_str().filter(|v| !v.is_empty()) {
        let h = Path::new(h).canonicalize()?;
        if canonical.starts_with(&h) || h.starts_with(&canonical) {
            return fail(422, "BACKUP_DIRECTORY_CONFLICT");
        }
    }
    files::writable_directory(path)?;
    Ok(())
}
pub(super) fn list(s: &Service, requested: &str) -> Result<Value> {
    let path = if requested.is_empty() {
        Path::new(
            s.config["backup_dir"]
                .as_str()
                .ok_or_else(|| Error::new(422, "BACKUP_PATH_INVALID"))?,
        )
    } else {
        Path::new(requested)
    };
    files::dir(path)?;
    let mut directories = Vec::new();
    let mut truncated = false;
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        if entry.path().is_dir() {
            if directories.len() == 500 {
                truncated = true;
                break;
            }
            directories.push(entry.path());
        }
    }
    directories.sort();
    #[cfg(windows)]
    let roots: Vec<PathBuf> = ('C'..='Z')
        .map(|d| PathBuf::from(format!("{d}:\\")))
        .filter(|p| p.is_dir())
        .collect();
    #[cfg(not(windows))]
    let roots = vec![PathBuf::from("/")];
    Ok(
        json!({"path":path,"parent":path.parent(),"directories":directories,"roots":roots,"truncated":truncated}),
    )
}
