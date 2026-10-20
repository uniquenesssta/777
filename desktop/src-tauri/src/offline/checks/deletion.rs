use super::*;
#[test]
fn downloaded_deletion_hides_pending_order_and_retains_unsent_changes() {
    let f = Fixture::new();
    let saved = f.local.save("save", &f.body()).unwrap();
    let id = saved["order_id"].as_str().unwrap();
    let mut view = f.local.order(id).unwrap();
    let old = view.clone();
    view["deleted"] = json!(true);
    view["state"] = json!("void");
    view["revision"] = json!("2");
    f.local.receive_order(view.clone()).unwrap();
    assert_eq!(f.local.listing("", "", 0, "").unwrap()["total"], 0);
    assert_eq!(f.local.customers("", 0, None, 0, None).unwrap()["total"], 0);
    assert_eq!(f.local.order(id).unwrap_err().code, "NOT_FOUND");
    assert_eq!(f.local.upload().unwrap().len(), 1); // Never silently erase unuploaded input.
    assert!(f
        .local
        .save(
            "note",
            &json!({"order_id":id,"expected_revision":"2","body":"cannot restore"})
        )
        .is_err());
    f.local.receive_order(old).unwrap();
    assert_eq!(f.local.listing("", "", 0, "").unwrap()["total"], 0);
    let reopened = Local::open(f.root.join("offline.sqlite3"), !cfg!(windows)).unwrap();
    assert_eq!(reopened.listing("", "", 0, "").unwrap()["total"], 0);
}
