use crate::automatic_support::Fixture;
use quote_host::{automatic as a, recovery};
use quote_ledger::store;
use serde_json::{json, Value};
fn draft() -> Value {
    json!({"request_id":store::uid().unwrap(),"snapshot":{"price_version_id":"fixture","lines":[{"line_kind":"normal","product_id":"P","q":"1","h":"","w":"","name":""}],"rule_version":"business-v1","numeric_profile":"numeric-v1"},"details":{"customer":"customer","order_ref":"1","wechat":"wx"}})
}
#[test]
fn host_redacts_limited_manager_and_blocks_financial_output_downloads_retries_and_receipts() {
    let mut f = Fixture::new();
    f.service.handle("POST","/v1/prices",&f.legacy_token,&json!({"request_id":store::uid().unwrap(),"expected_price_version_id":null,"prices":{"price_version_id":"fixture","items":[{"product_id":"P","sale":"10","cost":"4","k":"1","single":true}]}}),"","fixture").unwrap();
    let (package, secret, _) = f.package("manager", &["quote", "orders", "exports"], 3);
    let (d, s) = f.candidate(&package);
    let session = f.activate(&d, &secret, &s);
    let token = session["token"].as_str().unwrap();
    let order = f
        .service
        .handle("POST", "/v1/orders", token, &draft(), "", "fixture")
        .unwrap();
    assert!(order.get("cost_cents").is_none());
    let id = order["order_id"].as_str().unwrap();
    let detail = f
        .service
        .handle(
            "GET",
            &format!("/v1/orders/{id}"),
            token,
            &Value::Null,
            "",
            "fixture",
        )
        .unwrap();
    assert!(!detail.to_string().contains("cost_cents"));
    let admin = f.service.auth.authenticate(&f.legacy_token).unwrap();
    let original = f.service.order(&admin, id).unwrap();
    let rid = store::uid().unwrap();
    let job = f
        .service
        .outputs
        .as_ref()
        .unwrap()
        .enqueue(
            &admin,
            &json!({"request_id":rid,"order_id":id,"expected_revision":1,"kind":"excel_admin"}),
            original,
        )
        .unwrap();
    let jid = job["job_id"].as_str().unwrap();
    for tail in ["", "/content", "/location", "/retry"] {
        assert!(f
            .service
            .handle(
                if tail == "/retry" { "POST" } else { "GET" },
                &format!("/v1/outputs/{jid}{tail}"),
                token,
                &json!({"request_id":store::uid().unwrap()}),
                "",
                "fixture"
            )
            .is_err());
    }
    let list = f
        .service
        .handle("GET", "/v1/outputs", token, &Value::Null, "", "fixture")
        .unwrap();
    assert_eq!(list["total"], 0);
    assert!(f
        .service
        .handle(
            "GET",
            &format!("/v1/requests/{rid}"),
            token,
            &Value::Null,
            "",
            "fixture"
        )
        .is_err());
    let backup = recovery::capture(&f.service, "2026-10-19").unwrap();
    let raw = String::from_utf8(recovery::encode(&backup).unwrap()).unwrap();
    for value in [&secret, &s, &f.issuer_secret] {
        assert!(!raw.contains(value));
    }
    assert!(backup.users.rows.iter().any(|r| r[0] == session["subject"]));
}
#[test]
fn two_sales_devices_do_not_share_orders_or_customer_matches() {
    let mut f = Fixture::new();
    f.service.handle("POST","/v1/prices",&f.legacy_token,&json!({"request_id":store::uid().unwrap(),"expected_price_version_id":null,"prices":{"price_version_id":"fixture","items":[{"product_id":"P","sale":"10","cost":"4","k":"1","single":true}]}}),"","fixture").unwrap();
    let (package, secret, _) = f.package("sales", &["quote", "orders"], 3);
    let (d1, s1) = f.candidate(&package);
    let (d2, s2) = f.candidate(&package);
    let t1 = f.activate(&d1, &secret, &s1);
    let t2 = f.activate(&d2, &secret, &s2);
    let t1 = t1["token"].as_str().unwrap();
    let t2 = t2["token"].as_str().unwrap();
    let first = f
        .service
        .handle("POST", "/v1/orders", t1, &draft(), "", "fixture")
        .unwrap();
    let id = first["order_id"].as_str().unwrap();
    assert!(f
        .service
        .handle(
            "GET",
            &format!("/v1/orders/{id}"),
            t2,
            &Value::Null,
            "",
            "fixture"
        )
        .is_err());
    let list = f
        .service
        .handle("GET", "/v1/orders", t2, &Value::Null, "", "fixture")
        .unwrap();
    assert!(!list.to_string().contains(id));
    let groups = f
        .service
        .handle(
            "POST",
            "/v1/customer-orders",
            t2,
            &json!({"query":"wx","offset":0}),
            "",
            "fixture",
        )
        .unwrap();
    assert_eq!(groups["total"], 0);
    assert!(f
        .service
        .handle(
            "POST",
            "/v1/order-save",
            t1,
            &json!({"order_id":id}),
            "",
            "fixture"
        )
        .is_err());
    assert!(a::permissions::validate("sales", &["finance".into(), "quote".into()]).is_err());
}
