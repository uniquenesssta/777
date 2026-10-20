//! Open a file saved and verified by the local export workflow.
use crate::{DesktopError, Result};
pub fn open(path: &str) -> Result<()> {
    let target = std::path::Path::new(path);
    if !target.is_absolute() || !target.is_file() {
        return Err(DesktopError::new(409, "OUTPUT_LOCATION_UNAVAILABLE"));
    }
    crate::journal::check(target)?;
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
