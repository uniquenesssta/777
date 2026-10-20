use super::*;
#[test]
fn same_command_after_a_lost_ui_reply_replays_the_original_and_rejects_changed_body() {
    let f = Fixture::new();
    let mut body = f.body();
    body["operation_id"] = json!(crate::types::new_id().unwrap());
    let saved = f.local.save("save", &body).unwrap();
    let reopened = Local::open(f.root.join("offline.sqlite3"), !cfg!(windows)).unwrap();
    assert_eq!(reopened.save("save", &body).unwrap(), saved);
    assert_eq!(
        reopened
            .saved_receipt(body["operation_id"].as_str().unwrap())
            .unwrap()["result"],
        saved
    );
    body["snapshot"]["lines"][0]["q"] = json!("2");
    assert_eq!(
        reopened.save("save", &body).unwrap_err().code,
        "LOCAL_COMMAND_ID_CONFLICT"
    );
    assert_eq!(
        reopened
            .c
            .query_row("SELECT count(*) FROM local_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
#[test]
fn a_long_blocked_chain_does_not_hide_a_later_unrelated_order() {
    let f = Fixture::new();
    let first = f.local.save("save", &f.body()).unwrap();
    let id = first["order_id"].as_str().unwrap();
    for n in 1..35 {
        f.local.save("note",&json!({"order_id":id,"expected_revision":n.to_string(),"body":format!("note {n}")})).unwrap();
    }
    let mut other = f.body();
    other["details"]["order_ref"] = json!("unrelated");
    let second = f.local.save("save", &other).unwrap();
    let upload = f.local.upload().unwrap();
    assert_eq!(upload.len(), 2);
    assert!(upload.iter().any(|v| v["order_id"] == second["order_id"]));
}
#[test]
fn an_explicit_self_customer_anchor_does_not_wait_on_its_own_edit() {
    let f = Fixture::new();
    let first = f.local.save("save", &f.body()).unwrap();
    let op = f.local.upload().unwrap()[0].clone();
    let mut edit = f.body();
    edit["order_id"] = first["order_id"].clone();
    edit["expected_revision"] = json!("1");
    let order = f.local.order(first["order_id"].as_str().unwrap()).unwrap();
    edit["sources"] = json!([order["lines"][0]["line_id"]]);
    edit["customer"] = json!({"customer_id":order["customer_id"]});
    edit["snapshot"]["lines"][0]["q"] = json!("2");
    f.local.save("save", &edit).unwrap();
    f.local.receipts(&json!([{"operation_id":op["operation_id"],"content_sha256":op["content_sha256"],"state":"applied","result":{"order_id":first["order_id"],"revision":"1"}}])).unwrap();
    let upload = f.local.upload().unwrap();
    assert_eq!(upload.len(), 1);
    assert_eq!(upload[0]["kind"], "edit");
}
#[test]
fn transport_lock_is_independent_of_business_writes_and_released_on_drop() {
    let f = Fixture::new();
    let peer = Local::open(f.root.join("offline.sqlite3"), !cfg!(windows)).unwrap();
    let guard = f.local.sync_guard().unwrap().unwrap();
    assert!(peer.sync_guard().unwrap().is_none());
    peer.save("save", &f.body()).unwrap();
    drop(guard);
    assert!(peer.sync_guard().unwrap().is_some());
}
#[test]
fn shared_payload_validation_prevents_locally_committing_an_unuploadable_customer() {
    let f = Fixture::new();
    let mut body = f.body();
    body["customer"] = json!({"arbitrary":"not allowed"});
    assert!(f.local.save("save", &body).is_err());
    assert_eq!(
        f.local
            .c
            .query_row("SELECT count(*) FROM local_orders", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
