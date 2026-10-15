use quote_core::{
    calculation::calculate,
    configuration::{parse_config, Source},
    models::*,
    pricing::unit_sale,
};
use serde_json::json;

#[test]
fn final_price_modes_do_not_apply_k_twice_and_legacy_stays_exact() {
    for (mode, cents) in [
        (None, 4000),
        (Some("manual"), 2000),
        (Some("cost_plus"), 2300),
    ] {
        let mut item = json!({"product_id":"P","sale":"20","cost":"11.5","k":"2","single":true});
        if let Some(mode) = mode {
            item["pricing_mode"] = json!(mode);
        }
        let prices: Prices =
            serde_json::from_value(json!({"price_version_id":"v1","items":[item]})).unwrap();
        let quote: Quote = serde_json::from_value(
            json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":"1"}]}),
        )
        .unwrap();
        let r = calculate(&quote, &prices);
        assert_eq!(r.totals.unwrap().income(), cents);
        assert_eq!(
            serde_json::to_value(&prices.items[0])
                .unwrap()
                .get("pricing_mode")
                .is_some(),
            mode.is_some()
        );
    }
}
#[test]
fn automatic_unit_keeps_subcents_until_line_settlement_and_ignores_forged_sale() {
    let source = r#"{"items":[{"name":"P","sale":"forged","cost":"0.335","k":"3","single":true,"pricing_mode":"cost_plus"}]}"#;
    let p = parse_config(Source::Text(source), &json!("v1"), None)
        .config
        .unwrap()
        .prices;
    assert_eq!(p.items[0].sale, "1.005");
    assert_eq!(unit_sale(&p.items[0]).unwrap().text(), "1.005");
    let q: Quote = serde_json::from_value(
        json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":"3"}]}),
    )
    .unwrap();
    assert_eq!(calculate(&q, &p).totals.unwrap().income(), 302);
}
#[test]
fn automatic_price_allows_zero_and_exact_large_product_and_rejects_unknown_modes() {
    for (cost, k, expected) in [
        ("0", "2", "0"),
        ("11.5", "0", "0"),
        ("11.5", "", "11.5"),
        ("1000000000", "1000000000", "1000000000000000000"),
    ] {
        let raw=json!({"items":[{"name":"P","sale":"","cost":cost,"k":k,"single":true,"pricing_mode":"cost_plus"}]}).to_string();
        let p = parse_config(Source::Text(&raw), &json!("v1"), None)
            .config
            .unwrap()
            .prices;
        assert_eq!(p.items[0].sale, expected);
    }
    let raw =
        r#"{"items":[{"name":"P","sale":"20","cost":"11.5","k":"2","pricing_mode":"unknown"}]}"#;
    assert_eq!(
        parse_config(Source::Text(raw), &json!("v1"), None).status,
        "VALIDATION"
    );
}
