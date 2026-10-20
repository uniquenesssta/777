use super::*;
fn listing(f: &mut Fixture, history: bool) -> Value {
    f.post(
        "/v1/developer/orders/list",
        json!({"query":"","offset":0,"history":history}),
    )
}
fn command(f: &mut Fixture, order: &Value) -> Value {
    json!({"ledger_id":listing(f,false)["ledger_id"],"request_id":store::uid().unwrap(),"order_id":order["order_id"],"expected_revision":order["revision"],"reason":"清理测试订单"})
}
#[test]
fn developer_deletion_is_durable_idempotent_audited_and_excluded_from_queries_and_backup_excel() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    let first = f.post("/v1/order-save", draft("v1", "first"));
    let mut second = draft("v1", "second");
    second["customer"] = json!({"customer_id":first["customer_id"]});
    let second = f.post("/v1/order-save", second);
    assert_eq!(f.get("/v1/orders")["total"], 2); // Populate incremental cache before delete.
    let cmd = command(&mut f, &first);
    let result = f.post("/v1/developer/orders/delete", cmd.clone());
    assert_eq!(f.post("/v1/developer/orders/delete", cmd.clone()), result);
    let list = f.get("/v1/orders");
    assert_eq!(list["total"], 1);
    assert_eq!(list["totals"]["income_cents"], "1000");
    assert_eq!(list["orders"][0]["order_id"], second["order_id"]);
    let groups = f.post("/v1/customer-orders", json!({"query":"","offset":0}));
    assert_eq!(groups["groups"][0]["total"], 1);
    let history = listing(&mut f, true);
    assert_eq!(history["total"], 1);
    assert_eq!(history["orders"][0]["reason"], "清理测试订单");
    assert!(history["orders"][0]["deleted_by"].is_string());
    let c = store::open(&f.s.ledger, true).unwrap();
    let inv = integrity::inventory(&c).unwrap();
    assert_eq!(inv["active_income_cents"], "1000");
    assert_eq!(inv["counts"]["orders"], 2);
    assert!(c
        .execute(
            "DELETE FROM audit_events WHERE operation='delete_order'",
            []
        )
        .is_err());
    drop(c);
    let actor = f.s.auth.authenticate(&f.token).unwrap();
    assert_eq!(
        f.s.order(&actor, first["order_id"].as_str().unwrap())
            .unwrap_err()
            .status,
        404
    );
    f.s.queries = Queries::new().unwrap();
    assert_eq!(f.get("/v1/orders")["total"], 1); // Cold reload agrees with incremental cache.
    let data = recovery::capture(&f.s, "2026-10-21").unwrap();
    let decoded = recovery::decode(&recovery::encode(&data).unwrap()).unwrap();
    let restored = f.root.join("deleted-restored.sqlite3");
    recovery::restore_ledger(&decoded, &restored).unwrap();
    let restored_connection = store::open(&restored, false).unwrap();
    assert_eq!(integrity::inventory(&restored_connection).unwrap(), inv);
    assert!(quote_ledger::deletion::deleted(
        &restored_connection,
        first["order_id"].as_str().unwrap()
    )
    .unwrap());
    let readable =
        quote_excel::readable::backup_orders(&serde_json::to_value(&decoded).unwrap()).unwrap();
    assert_eq!(readable.len(), 1);
    assert_eq!(readable[0]["order_id"], second["order_id"]);
    assert!(decoded.ledger["audit_events"]
        .rows
        .iter()
        .any(|r| r.iter().any(|v| v == "delete_order")));
    let cmd2 = command(&mut f, &second);
    f.post("/v1/developer/orders/delete", cmd2);
    assert_eq!(
        f.post("/v1/customer-orders", json!({"query":"","offset":0}))["total"],
        0
    );
    // Deleted customer aliases cannot strand new quotes in a missing-choice prompt.
    assert!(f.post("/v1/order-save", draft("v1", "first"))["order_id"].is_string());
}
#[test]
fn deletion_rejects_stale_cross_ledger_unauthorized_and_restore_attempts() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    let first = f.post("/v1/order-save", draft("v1", "first"));
    let cmd = command(&mut f, &first);
    for (key, value) in [
        ("expected_revision", json!(9)),
        ("ledger_id", json!(store::uid().unwrap())),
        ("reason", json!(" ")),
    ] {
        let mut bad = cmd.clone();
        bad[key] = value;
        assert!(f
            .s
            .handle(
                "POST",
                "/v1/developer/orders/delete",
                &f.token,
                &bad,
                "",
                "test"
            )
            .is_err());
        assert_eq!(f.get("/v1/orders")["total"], 1);
    }
    assert!(f
        .s
        .handle(
            "POST",
            "/v1/developer/orders/delete",
            "invalid",
            &cmd,
            "",
            "test"
        )
        .is_err());
    let mut changed = cmd.clone();
    f.post("/v1/developer/orders/delete", cmd);
    changed["reason"] = json!("different");
    assert!(f
        .s
        .handle(
            "POST",
            "/v1/developer/orders/delete",
            &f.token,
            &changed,
            "",
            "test"
        )
        .is_err());
    for (path, body) in [
        (
            "/v1/state",
            json!({"request_id":store::uid().unwrap(),"order_id":first["order_id"],"expected_revision":2,"state":"active","reason":"try restore"}),
        ),
        (
            "/v1/notes",
            json!({"request_id":store::uid().unwrap(),"order_id":first["order_id"],"expected_revision":2,"body":"try edit"}),
        ),
    ] {
        assert_eq!(
            f.s.handle("POST", path, &f.token, &body, "", "test")
                .unwrap_err()
                .code,
            "ORDER_DELETED"
        );
    }
    assert_eq!(f.get("/v1/orders")["total"], 0);
}
