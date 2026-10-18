//! Local deployment ownership; IP alone never authorizes replacement.
use super::*;
use std::path::Path;
pub fn verify(root: &Path, auxiliary: bool) -> Result<Value> {
    files::dir(root)?;
    for ancestor in root.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if metadata.file_type().is_symlink() {
            return fail(409, "HOST_ROOT_REPARSE_POINT");
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return fail(409, "HOST_ROOT_REPARSE_POINT");
            }
        }
    }
    #[cfg(windows)]
    {
        use std::path::{Component, Prefix};
        if !matches!(root.components().next(),Some(Component::Prefix(p)) if matches!(p.kind(),Prefix::Disk(_)|Prefix::VerbatimDisk(_)))
        {
            return fail(422, "LOCAL_HOST_ROOT_REQUIRED");
        }
    }
    let d = files::read_json(&root.join("private/deployment.json"))?;
    let saved = d["root"].as_str().ok_or_else(denied)?;
    if d["schema"] != "777-site-deployment-v1"
        || std::path::Path::new(saved).canonicalize()? != root.canonicalize()?
    {
        return fail(409, "DEPLOYMENT_OWNER_OR_IDENTITY_CONFLICT");
    }
    #[cfg(windows)]
    {
        let output = std::process::Command::new(
            std::path::PathBuf::from(std::env::var_os("SystemRoot").ok_or_else(denied)?)
                .join("System32/WindowsPowerShell/v1.0/powershell.exe"),
        )
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ])
        .output()?;
        let sid = String::from_utf8_lossy(&output.stdout);
        if auxiliary
            || !output.status.success()
            || d["owner_sid"] != sid.trim()
            || d["machine"].as_str() != std::env::var("COMPUTERNAME").ok().as_deref()
        {
            return fail(409, "DEPLOYMENT_OWNER_OR_IDENTITY_CONFLICT");
        }
    }
    #[cfg(not(windows))]
    if !auxiliary {
        return fail(400, "WINDOWS_HOST_REQUIRED");
    }
    for (file, key) in [
        ("host-run.ps1", "runner_sha256"),
        ("host-identity.ps1", "identity_sha256"),
    ] {
        if files::sha(&root.join("private").join(file))? != d[key] {
            return fail(409, "HOST_DEPLOYMENT_RESOURCE_CHANGED");
        }
    }
    Ok(d)
}
pub fn replace_file(source: &Path, target: &Path) -> Result<()> {
    let stage = target.with_extension(format!("{}.partial", store::uid()?));
    let result = (|| {
        files::copy(source, &stage)?;
        std::fs::rename(&stage, target)?;
        Ok(())
    })();
    if stage.exists() {
        let _ = std::fs::remove_file(stage);
    }
    result
}

/// A crash before journal publication must not turn retained originals into conflicts.
pub fn retain(source: &Path, target: &Path) -> Result<()> {
    if target.exists() {
        if files::sha(source)? != files::sha(target)? {
            return fail(409, "UPGRADE_BACKUP_CONFLICT");
        }
        return Ok(());
    }
    replace_file(source, target)
}
