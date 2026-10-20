use super::*;
#[test]
fn quote_identity_is_exact_field_scoped_and_order_numbers_do_not_select_customers() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    f.post("/v1/order-save", draft("v1", "only-order-ref"));
    let mut other = draft("v1", "other-order");
    other["details"]["customer"] = json!("淘宝0002");
    other["details"]["wechat"] = json!("wx0002");
    f.post("/v1/order-save", other);
    for (customer, wechat, count) in [
        ("淘宝0001", "", 1),
        ("", "wx0001", 1),
        ("淘宝0001", "wx0001", 1),
        ("淘宝0001", "wx0002", 2),
        ("only-order-ref", "", 0),
        ("wx0001", "", 0),
        ("", "淘宝0001", 0),
        ("淘宝000", "", 0),
        ("", "", 0),
    ] {
        let result = f.post(
            "/v1/customer-orders",
            json!({"query":"","offset":0,"identity":{"customer":customer,"wechat":wechat}}),
        );
        assert_eq!(result["total"], count, "{customer}/{wechat}");
    }
    // Order history still supports searching order numbers, separately from quote identity.
    assert_eq!(
        f.post(
            "/v1/customer-orders",
            json!({"query":"only-order-ref","offset":0})
        )["total"],
        1
    );
    let mut new_customer = draft("v1", "only-order-ref");
    new_customer["details"]["customer"] = json!("different buyer");
    new_customer["details"]["wechat"] = json!("different contact");
    assert!(f.post("/v1/order-save", new_customer)["order_id"].is_string());
}
