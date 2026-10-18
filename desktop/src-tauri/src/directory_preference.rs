//! A directory suggestion only: no filesystem probing, creation, or service mutation.
use crate::{journal::Store, types::identifier, DesktopError, Result};
use serde_json::{json, Value};

pub(crate) fn preference(store: &Store, ledger: &str, directory: Option<String>) -> Result<Value> {
    identifier(ledger)?;
    let name = format!("business-directory-{ledger}.bin");
    if let Some(value) = directory {
        if value.len() > 32767 || value.chars().any(|c| c.is_control()) {
            return Err(DesktopError::new(422, "INVALID_DIRECTORY_PREFERENCE"));
        }
        // Preserve the exact input; display aliases must never overwrite it.
        store.replace(&name, &value)?;
    }
    Ok(
        json!({"ledger_id":ledger,"directory":store.read::<String>(&name)?.unwrap_or_default(),"applied":false}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preferences_survive_restart_and_are_isolated_without_touching_target() {
        let root = std::env::temp_dir().join(format!(
            "777-preferences-{}",
            crate::types::new_id().unwrap()
        ));
        let target = root.join("must-not-exist");
        let a = crate::types::new_id().unwrap();
        let b = crate::types::new_id().unwrap();
        let store = Store::new(root.clone(), !cfg!(windows)).unwrap();
        preference(&store, &a, Some(target.to_string_lossy().into_owned())).unwrap();
        assert!(!target.exists());
        drop(store);
        let store = Store::new(root.clone(), !cfg!(windows)).unwrap();
        assert_eq!(
            preference(&store, &a, None).unwrap()["directory"],
            target.to_string_lossy().as_ref()
        );
        assert_eq!(preference(&store, &b, None).unwrap()["directory"], "");
        assert!(preference(&store, "../bad", Some("x".into())).is_err());
        assert!(preference(&store, &a, Some("bad\npath".into())).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
