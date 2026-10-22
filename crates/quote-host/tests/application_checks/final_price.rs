use super::support::*;
use serde_json::json;
#[test]
fn final_price_upload_merge_and_conflicts_keep_actual_totals() {
    let a = App::new("manager");
    let mut first = a.op(1);
    first["payload"]["snapshot"]["final_price"] = json!("8.25");
    let first = seal(first);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&first), "applied");
    assert_eq!(a.order(&first)["income_cents"], "825");
    assert_eq!(a.inventory()["active_income_cents"], "825");
    let feed = a
        .call(
            "/v1/offline/changes",
            &json!({"protocol":quote_host::intake::FORMAT,"cursor":null}),
        )
        .unwrap();
    let chunk=a.call("/v1/offline/order-chunk",&json!({"protocol":quote_host::intake::FORMAT,"epoch":feed["epoch"],"order_id":first["order_id"],"revision":"1","section":"lines","offset":"0"})).unwrap();
    assert_eq!(chunk["order"]["final_price"], "8.25");

    let mut price = edit(&a, &first, 2, 1, json!({}), json!([]));
    price["payload"]["final_price"] = json!("7.50");
    let price = seal(price);
    a.send(vec![price.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&price), "applied");
    let detail = edit(
        &a,
        &first,
        3,
        1,
        json!({"order_ref":"updated-reference"}),
        json!([]),
    );
    a.send(vec![detail.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&detail), "applied");
    assert_eq!(a.order(&first)["income_cents"], "750");
    let conflict = edit(
        &a,
        &first,
        4,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "2")]),
    );
    a.send(vec![conflict.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&conflict), "conflict");
    let mut other = edit(&a, &first, 5, 1, json!({}), json!([]));
    other["payload"]["final_price"] = json!("9");
    let other = seal(other);
    a.send(vec![other.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&other), "conflict");
    let mut clear = edit(&a, &first, 6, 3, json!({}), json!([]));
    clear["payload"]["final_price"] = json!(null);
    let clear = seal(clear);
    a.send(vec![clear.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&clear), "applied");
    assert_eq!(a.order(&first)["income_cents"], "1000");
    assert_eq!(a.inventory()["active_income_cents"], "1000");
}
