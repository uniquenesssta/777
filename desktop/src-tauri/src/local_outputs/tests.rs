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
    let raw = b"\xff\xd8\xffchecked-content\xff\xd9";
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

#[test]
fn old_export_history_uses_original_order_reference() {
    let temp =
        std::env::temp_dir().join(format!("quote-local-{}", crate::types::new_id().unwrap()));
    let store = Store::new(temp.join("profile"), !cfg!(windows)).unwrap();
    let id = crate::types::new_id().unwrap();
    let order_id = crate::types::new_id().unwrap();
    let snapshot = json!({"job_id":id,"kind":"quote_png","order":{"order_id":order_id,"details":{"order_ref":"TB-000123"}}});
    let mut job = jobs::insert(&store, "scope", &snapshot).unwrap();
    job.as_object_mut().unwrap().remove("order_ref");
    jobs::update(&store, "scope", &job).unwrap();
    let page = jobs::list(&store, "scope", 0).unwrap();
    assert_eq!(page["jobs"][0]["order_ref"], "TB-000123");
    assert_eq!(page["jobs"][0]["order_id"], order_id);
    assert_ne!(page["jobs"][0]["order_id"], id);
    std::fs::remove_dir_all(temp).unwrap();
}
