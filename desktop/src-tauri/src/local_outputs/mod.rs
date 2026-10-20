//! Per-computer export destination, independent of Host business storage.
mod files;
mod image;
pub(crate) mod jobs;
mod render;
pub(crate) use render::execute;
pub(crate) use render::set_font;
#[cfg(test)]
mod tests;
use crate::{journal::Store, DesktopError, Result};
pub(crate) use files::save;
use serde_json::{json, Value};
use std::path::PathBuf;
const CONFIG: &str = "local-output-root.bin";
pub(crate) fn folder(kind: &str) -> Result<(&'static str, &'static str)> {
    match kind {
        "quote_png" => Ok(("PIC", ".jpg")),
        "excel_quote" => Ok(("Excel", ".xlsx")),
        "excel_admin" | "excel_period" => Ok(("内部财务报表", ".xlsx")),
        _ => Err(DesktopError::new(422, "INVALID_OUTPUT_KIND")),
    }
}
pub(crate) fn root(store: &Store) -> Result<PathBuf> {
    let path = store.read::<String>(CONFIG)?.unwrap_or_default();
    if path.is_empty() {
        return Err(DesktopError::new(409, "LOCAL_OUTPUT_ROOT_REQUIRED"));
    }
    Ok(PathBuf::from(path))
}
pub(crate) fn settings(store: &Store, value: Option<&str>) -> Result<Value> {
    if let Some(value) = value {
        let path = PathBuf::from(value);
        if !path.is_absolute() || value.len() > 32767 || value.chars().any(char::is_control) {
            return Err(DesktopError::new(422, "INVALID_DIRECTORY_PREFERENCE"));
        }
        files::prepare(&path)?;
        store.replace(CONFIG, &value)?;
    }
    let root = store.read::<String>(CONFIG)?.unwrap_or_default();
    let child = |name: &str| {
        if root.is_empty() {
            String::new()
        } else {
            PathBuf::from(&root)
                .join(name)
                .to_string_lossy()
                .into_owned()
        }
    };
    Ok(
        json!({"root":root,"image_dir":child("PIC"),"export_dir":child("Excel"),"report_dir":child("内部财务报表")}),
    )
}
