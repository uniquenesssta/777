use super::*;
#[test]
fn final_price_save_edit_clear_history_and_backup_preserve_actual_income() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "100");
    let mut body = draft("v1", "agreed");
    body["snapshot"]["final_price"] = json!("80.25");
    body["snapshot"]["lines"]
        .as_array_mut()
        .unwrap()
        .push(json!({"line_kind":"discount","percent":"90%","name":""}));
    body["sources"] = json!([null, null]);
    let saved = f.post("/v1/order-save", body.clone());
    assert_eq!(saved["income_cents"], "8025");
    let id = saved["order_id"].as_str().unwrap();
    let order = f.get(&format!("/v1/orders/{id}"));
    assert_eq!(order["final_price"], "80.25");
    assert_eq!(order["profit_cents"], "7625");
    assert_eq!(order["lines"][0]["income_cents"], "10000");
    assert_eq!(order["lines"][1]["income_cents"], "-1000");
    let public = quote_host::outputs::public_order(order.clone());
    assert_eq!(public["final_price"], "80.25");
    assert!(public.get("cost_cents").is_none());
    let data = recovery::capture(&f.s, "2026-10-22").unwrap();
    let readable =
        quote_excel::readable::backup_orders(&serde_json::to_value(&data).unwrap()).unwrap();
    assert_eq!(readable[0]["final_price"], "80.25");
    let bytes=quote_excel::write::write(&json!({"format":"777-output-v1","kind":"excel_period","job_id":store::uid().unwrap(),"orders":readable,"range":{"from":"2026-10-01","to":"2026-10-31"}})).unwrap();
    let report = serde_json::to_string(&quote_excel::read::read(&bytes).unwrap()).unwrap();
    for expected in ["成交调价", "80.25", "76.25", "-9.75"] {
        assert!(report.contains(expected), "{expected}");
    }
    let restored = f.root.join("final-restored.sqlite3");
    recovery::restore_ledger(
        &recovery::decode(&recovery::encode(&data).unwrap()).unwrap(),
        &restored,
    )
    .unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&restored, false).unwrap()).unwrap()
            ["active_income_cents"],
        "8025"
    );
    body["request_id"] = json!(store::uid().unwrap());
    body["order_id"] = json!(id);
    body["expected_revision"] = json!(1);
    body["customer"] = json!({"customer_id":saved["customer_id"]});
    body["sources"] = json!([order["lines"][0]["line_id"], order["lines"][1]["line_id"]]);
    body["snapshot"]
        .as_object_mut()
        .unwrap()
        .remove("final_price");
    assert_eq!(f.post("/v1/order-save", body)["income_cents"], "9000");
    let history = f.get(&format!("/v1/orders/{id}/changes/1"));
    assert!(history["changes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|c| c["field"] == "最终成交价" && c["before"] == "80.25"));
    assert!(f.get(&format!("/v1/orders/{id}"))["final_price"].is_null());
}
