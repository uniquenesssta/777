//! Only unpublished initialization owned by a protected intent can be rebuilt.
use crate::{
    automatic::{denied, issuer_state},
    fail, files,
    host::{self, Init},
    Result,
};
use serde_json::json;
use std::path::{Path, PathBuf};
fn no_links(path: &Path) -> Result<()> {
    let m = std::fs::symlink_metadata(path)?;
    if m.file_type().is_symlink() {
        return fail(409, "HOST_ROOT_REPARSE_POINT");
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if m.file_attributes() & 0x400 != 0 {
            return fail(409, "HOST_ROOT_REPARSE_POINT");
        }
    }
    if m.is_dir() {
        for entry in std::fs::read_dir(path)? {
            no_links(&entry?.path())?;
        }
    }
    Ok(())
}
fn recover(
    state: &Path,
    root: &Path,
    node: &str,
    auxiliary: bool,
) -> Result<(PathBuf, serde_json::Value)> {
    let stage = state.join("initializing");
    let journal = state.join("initializing.bin");
    let mut intent = if journal.exists() {
        issuer_state::load(&journal, auxiliary)?
    } else {
        if stage.exists() {
            return fail(409, "CLUSTER_INITIALIZATION_NOT_OWNED");
        }
        json!({"format":"777-automatic-initialization-v1","root":root,"node_id":node,"phase":"initializing"})
    };
    if intent["format"] != "777-automatic-initialization-v1"
        || intent["root"] != json!(root)
        || intent["node_id"] != node
        || root.exists()
    {
        return fail(409, "CLUSTER_INITIALIZATION_NOT_OWNED");
    }
    if stage.exists() && intent["phase"] == "initializing" {
        // No snapshot or business runner ever targets this pre-publication directory.
        no_links(&stage)?;
        std::fs::remove_dir_all(&stage)?;
    }
    if !stage.exists() {
        intent["phase"] = json!("initializing");
        issuer_state::save(&journal, &intent, auxiliary)?;
    }
    Ok((stage, intent))
}
pub(super) fn initialize(init: &Init, state: &Path, node: &str) -> Result<PathBuf> {
    let (stage, mut intent) = recover(state, &init.root, node, init.auxiliary)?;
    if !stage.exists() {
        let mut temporary = init.clone();
        temporary.root = stage.clone();
        temporary.secret = crate::automatic::secret()?;
        host::initialize(temporary)?;
        intent["phase"] = json!("initialized");
        issuer_state::save(&state.join("initializing.bin"), &intent, init.auxiliary)?;
    }
    if intent["phase"] != "initialized" {
        return Err(denied());
    }
    files::dir(&stage)?;
    Ok(stage)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_staging_and_existing_live_roots_are_never_removed() {
        let root = std::env::temp_dir().join(format!(
            "777-initializing-{}",
            quote_ledger::store::uid().unwrap()
        ));
        std::fs::create_dir(&root).unwrap();
        let stage = root.join("initializing");
        std::fs::create_dir(&stage).unwrap();
        std::fs::write(stage.join("keep"), b"keep").unwrap();
        assert!(recover(&root, &root.join("live"), "node", !cfg!(windows)).is_err());
        assert!(stage.join("keep").exists());
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn interrupted_unpublished_initialization_reuses_the_same_node_and_preserves_other_files() {
        let root = std::env::temp_dir().join(format!(
            "777-initializing-{}",
            quote_ledger::store::uid().unwrap()
        ));
        std::fs::create_dir(&root).unwrap();
        let live = root.join("live");
        let (stage, _) = recover(&root, &live, "original-node", !cfg!(windows)).unwrap();
        std::fs::create_dir(&stage).unwrap();
        std::fs::write(stage.join("generated.partial"), b"partial").unwrap();
        std::fs::write(root.join("keep"), b"keep").unwrap();
        let (_, intent) = recover(&root, &live, "original-node", !cfg!(windows)).unwrap();
        assert_eq!(intent["node_id"], "original-node");
        assert!(!stage.exists());
        assert!(root.join("keep").exists());
        std::fs::create_dir(&live).unwrap();
        assert!(recover(&root, &live, "original-node", !cfg!(windows)).is_err());
        assert!(live.exists());
        std::fs::remove_dir_all(root).unwrap();
    }
}
