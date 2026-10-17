//! Opens only a location fetched from an authorized completed output record.
use crate::{DesktopError, Result};
fn allowed(path: &str, url: &str) -> Result<()> {
    if path.contains('\0') || path.is_empty() {
        return Err(DesktopError::new(409, "OUTPUT_LOCATION_UNAVAILABLE"));
    }
    let host = reqwest::Url::parse(url)
        .ok()
        .and_then(|u| u.host_str().map(str::to_string));
    let local = host
        .as_deref()
        .is_some_and(|h| h == "localhost" || h == "127.0.0.1" || h == "[::1]" || h == "::1");
    if !local && !path.starts_with(r"\\") {
        return Err(DesktopError::new(409, "OUTPUT_FOLDER_ON_HOST"));
    }
    Ok(())
}
pub fn open(path: &str, url: &str) -> Result<()> {
    allowed(path, url)?;
    #[cfg(windows)]
    {
        let target = std::path::Path::new(path);
        if !target.is_absolute() {
            return Err(DesktopError::new(409, "OUTPUT_LOCATION_UNAVAILABLE"));
        }
        let directory = target
            .parent()
            .filter(|p| p.is_dir())
            .ok_or_else(|| DesktopError::new(409, "OUTPUT_FOLDER_UNAVAILABLE"))?;
        std::process::Command::new("explorer.exe")
            .arg(directory)
            .spawn()
            .map_err(|_| DesktopError::new(503, "OUTPUT_FOLDER_UNAVAILABLE"))?;
        Ok(())
    }
    #[cfg(not(windows))]
    {
        Err(DesktopError::new(409, "WINDOWS_REQUIRED"))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn remote_host_local_drive_is_not_this_computer() {
        assert!(allowed(r"C:\private\report.xlsx", "https://192.168.1.2:18477").is_err());
        assert!(allowed(r"\\server\共享\report.xlsx", "https://192.168.1.2:18477").is_ok());
        assert!(allowed(r"C:\private\report.xlsx", "https://127.0.0.1:18477").is_ok());
    }
}
