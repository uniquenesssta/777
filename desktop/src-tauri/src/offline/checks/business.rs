use super::*;
#[test]
fn durable_formal_order_and_original_survive_reopen_and_continued_edits() {
    let f = Fixture::new();
    let receipt = f.local.save("save", &f.body()).unwrap();
    let id = receipt["order_id"].as_str().unwrap();
    assert_eq!(receipt["income_cents"], "1000");
    let first = f.local.upload().unwrap()[0].clone();
    let reopened = Local::open(f.root.join("offline.sqlite3"), !cfg!(windows)).unwrap();
    assert_eq!(reopened.order(id).unwrap()["income_cents"], "1000");
    let saved = reopened.order(id).unwrap();
    let mut edit = f.body();
    edit["order_id"] = json!(id);
    edit["expected_revision"] = json!("1");
    edit["sources"] = json!([saved["lines"][0]["line_id"]]);
    edit["snapshot"]["lines"][0]["q"] = json!("2");
    reopened.save("save", &edit).unwrap();
    let changed = reopened.order(id).unwrap();
    assert_eq!(changed["income_cents"], "2000");
    assert_eq!(changed["lines"][0]["line_id"], saved["lines"][0]["line_id"]);
    assert_eq!(reopened.upload().unwrap(), vec![first.clone()]);
    assert_eq!(reopened.history_summary(id).unwrap().len(), 1);
    assert!(changed.get("cost_cents").is_none());
    assert!(changed["lines"][0].get("profit_cents").is_none());
    let raw: Vec<u8> = reopened
        .c
        .query_row(
            "SELECT raw FROM local_operations WHERE id=?",
            [first["operation_id"].as_str()],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(reopened.decode(&raw).unwrap(), first);
}
#[test]
fn failed_transaction_never_leaves_an_order_or_queue_half_committed() {
    let f = Fixture::new();
    f.local.c.execute_batch("CREATE TRIGGER simulate_failed_write BEFORE INSERT ON local_orders BEGIN SELECT RAISE(ABORT,'simulated IO failure'); END;").unwrap();
    assert!(f.local.save("save", &f.body()).is_err());
    for table in ["local_orders", "local_operations", "local_history"] {
        assert_eq!(
            f.local
                .c
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        )
    }
}
#[test]
fn accepted_is_not_applied_and_originals_are_not_deleted_on_receipt() {
    let f = Fixture::new();
    f.local.save("save", &f.body()).unwrap();
    let op = f.local.upload().unwrap()[0].clone();
    let received = json!({"operation_id":op["operation_id"],"content_sha256":op["content_sha256"],"state":"received","applied":false});
    f.local.receipts(&json!([received])).unwrap();
    assert!(f.local.upload().unwrap().is_empty());
    assert_eq!(f.local.receipt_ids().unwrap().len(), 1);
    let received = json!({"operation_id":op["operation_id"],"content_sha256":op["content_sha256"],"state":"applied","applied":true,"result":{"order_id":op["order_id"],"revision":"1"}});
    f.local.receipts(&json!([received])).unwrap();
    assert_eq!(
        f.local
            .c
            .query_row("SELECT count(*) FROM local_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        f.local.order(op["order_id"].as_str().unwrap()).unwrap()["income_cents"],
        "1000"
    );
}
#[test]
fn a_confirmed_projection_never_overwrites_a_pending_local_order() {
    let f = Fixture::new();
    let receipt = f.local.save("save", &f.body()).unwrap();
    let id = receipt["order_id"].as_str().unwrap();
    let mut remote = f.local.order(id).unwrap();
    remote["income_cents"] = json!("9999");
    f.local.receive_order(remote).unwrap();
    assert_eq!(f.local.order(id).unwrap()["income_cents"], "1000");
    assert_eq!(
        f.local.confirmed_revision(id).unwrap().as_deref(),
        Some("1")
    );
}
