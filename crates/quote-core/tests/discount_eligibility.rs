use quote_core::{
    calculation::{calculate, calculate_with_prices},
    configuration::{parse_config, Source},
    models::{Prices, Quote},
};
use serde_json::{json, Value};
fn prices() -> Prices {
    serde_json::from_value(json!({"price_version_id":"v1","items":[
        {"product_id":"goods","sale":"100","cost":"40","k":"1","single":true},
        {"product_id":"service","sale":"50","cost":"20","k":"1","single":true,"discount_eligible":false}
    ]})).unwrap()
}
fn line(id: &str) -> Value {
    json!({"kind":"normal","product_id":id,"q":"1"})
}
fn discount(p: &str) -> Value {
    json!({"kind":"discount","percent":p})
}
fn quote(lines: Vec<Value>) -> Quote {
    serde_json::from_value(json!({"price_version_id":"v1","lines":lines})).unwrap()
}
#[test]
fn discounts_skip_exempt_rows_and_compound_in_the_displayed_order() {
    let p = prices();
    let q = quote(vec![
        line("goods"),
        line("service"),
        discount("90%"),
        line("goods"),
        discount("50%"),
    ]);
    let r = calculate(&q, &p);
    assert_eq!(r.totals.as_ref().unwrap().income(), 14500); // (100*.9+100)*.5 + 50
    assert_eq!(r.totals.unwrap().cost(), 10000);
    let ls = r.lines.unwrap();
    assert_eq!(ls[2].amounts.income(), -1000);
    assert_eq!(ls[4].amounts.income(), -9500);
    assert_eq!(ls[1].price.as_ref().unwrap().discount_eligible, Some(false));
    let reordered = quote(vec![
        discount("90%"),
        line("goods"),
        line("service"),
        line("goods"),
        discount("50%"),
    ]);
    assert_eq!(calculate(&reordered, &p).totals.unwrap().income(), 15000);
}
#[test]
fn old_prices_remain_byte_compatible_and_frozen_opt_out_survives_catalog_change() {
    let mut p = prices();
    assert!(serde_json::to_value(&p.items[0])
        .unwrap()
        .get("discount_eligible")
        .is_none());
    let frozen = p.items[1].clone();
    p.items[1].discount_eligible = Some(true);
    let q = quote(vec![line("service"), discount("50%")]);
    assert_eq!(calculate(&q, &p).totals.unwrap().income(), 2500);
    assert_eq!(
        calculate_with_prices(&q, &p, Some(&[Some(frozen), None]))
            .totals
            .unwrap()
            .income(),
        5000
    );
}
#[test]
fn config_validates_and_preserves_participation_flag() {
    for flag in [json!(true), json!(false), json!("false"), json!(0)] {
        let raw=json!({"items":[{"name":"P","sale":"10","cost":"4","single":true,"discount_eligible":flag}]}).to_string();
        let parsed = parse_config(Source::Text(&raw), &json!("v1"), None);
        if flag.is_boolean() {
            assert_eq!(
                parsed.config.unwrap().prices.items[0].discount_eligible,
                flag.as_bool()
            );
        } else {
            assert_eq!(parsed.status, "VALIDATION");
        }
    }
}
#[test]
fn rounding_and_fully_exempt_discount_keep_exact_cents() {
    let mut p = prices();
    p.items[0].sale = json!("0.05");
    let q = quote(vec![
        line("goods"),
        discount("50%"),
        line("service"),
        discount("50%"),
    ]);
    assert_eq!(calculate(&q, &p).totals.unwrap().income(), 5001);
    let q = quote(vec![line("service"), discount("0%"), discount("90%")]);
    let r = calculate(&q, &p);
    assert_eq!(r.totals.unwrap().income(), 5000);
    assert_eq!(r.warnings.len(), 2);
}
