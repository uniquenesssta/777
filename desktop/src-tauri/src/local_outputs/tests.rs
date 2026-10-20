use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use sha2::{Digest, Sha256};
#[test]
fn paths_persist_and_files_are_verified_without_overwriting() {
    let temp =
        std::env::temp_dir().join(format!("quote-local-{}", crate::types::new_id().unwrap()));
    let store = Store::new(temp.join("profile"), !cfg!(windows)).unwrap();
    let root = temp.join("exports");
    settings(&store, Some(root.to_str().unwrap())).unwrap();
    for name in ["PIC", "Excel", "内部财务报表"] {
        assert!(root.join(name).is_dir());
    }
    let id = crate::types::new_id().unwrap();
    let raw = b"\x89PNG\r\n\x1a\nchecked-content";
    let mut content = json!({"format":"777-output-v1","job_id":id,"size":raw.len(),"sha256":format!("{:x}",Sha256::digest(raw)),"data_base64":STANDARD.encode(raw)});
    let file = save(&root, &id, "quote_png", &content).unwrap();
    assert_eq!(file.parent().unwrap(), root.join("PIC"));
    assert_eq!(save(&root, &id, "quote_png", &content).unwrap(), file);
    std::fs::write(&file, b"user edited").unwrap();
    assert_eq!(
        save(&root, &id, "quote_png", &content).unwrap_err().code,
        "LOCAL_OUTPUT_FILE_CHANGED"
    );
    content["sha256"] = json!("bad");
    assert_eq!(
        save(&root, &id, "quote_png", &content).unwrap_err().code,
        "OUTPUT_CONTENT_INVALID"
    );
    drop(store);
    let store = Store::new(temp.join("profile"), !cfg!(windows)).unwrap();
    assert_eq!(
        settings(&store, None).unwrap()["root"],
        root.to_str().unwrap()
    );
    std::fs::remove_dir_all(temp).unwrap();
}
