//! Windows native lifetime, independent of WebView and Host replication.
mod startup;
mod worker;
use crate::{Desktop, DesktopError, Result};
pub use startup::ensure;
use std::path::PathBuf;
pub use worker::run;
fn failure() -> DesktopError {
    DesktopError::new(503, "BACKGROUND_START_UNAVAILABLE")
}
fn root() -> Result<PathBuf> {
    crate::formal_profile_root(&PathBuf::from(
        std::env::var_os("LOCALAPPDATA").ok_or_else(failure)?,
    ))
    .ok_or_else(failure)
}
