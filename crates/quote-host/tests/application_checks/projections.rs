use super::support::*;
use quote_host::intake::FORMAT;
use quote_ledger::store;
use serde_json::json;
#[test]
fn changes_and_order_sections_are_bounded_and_hide_private_financial_fields() {
    let a = App::new("sales");
    let mut first = a.op(1);
    let source = first["payload"]["snapshot"]["lines"][0].clone();
    first["payload"]["snapshot"]["lines"] = json!((0..130)
        .map(|_| {
            let mut l = source.clone();
            l["line_id"] = json!(store::uid().unwrap());
            l
        })
        .collect::<Vec<_>>());
    let first = seal(first);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let feed = a
        .call(
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":null}),
        )
        .unwrap();
    assert_eq!(feed["changes"].as_array().unwrap().len(), 1);
    let mut offset = json!("0");
    let mut ids = Vec::new();
    loop {
        let chunk=a.call("/v1/offline/order-chunk",&json!({"protocol":FORMAT,"epoch":feed["epoch"],"order_id":first["order_id"],"revision":"1","section":"lines","offset":offset})).unwrap();
        let text = store::encoded(&chunk);
        assert!(!text.contains("cost_cents"));
        assert!(!text.contains("profit_cents"));
        assert!(!text.contains("\"cost\""));
        assert!(text.len() < 1048576);
        let rows = chunk["items"].as_array().unwrap();
        assert!(rows.len() <= 64);
        ids.extend(
            rows.iter()
                .map(|r| r["line_id"].as_str().unwrap().to_owned()),
        );
        offset = chunk["next_offset"].clone();
        if offset.is_null() {
            break;
        }
    }
    assert_eq!(ids.len(), 130);
    assert_eq!(
        ids.iter().collect::<std::collections::HashSet<_>>().len(),
        130
    );
    let empty = a
        .call(
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":feed["cursor"]}),
        )
        .unwrap();
    assert!(empty["changes"].as_array().unwrap().is_empty());
    let mut bad = feed["cursor"].as_str().unwrap().to_owned();
    bad.push('x');
    assert_eq!(
        a.call(
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":bad})
        )
        .unwrap_err()
        .status,
        409
    );
}
#[test]
fn another_devices_cursor_and_another_owners_orders_are_rejected() {
    let a = App::new("sales");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let feed = a
        .call(
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":null}),
        )
        .unwrap();
    let (package, key, _) = a.f.package("sales", &["quote", "orders"], 8);
    let (body, secret) = a.f.candidate(&package);
    let session = a.f.activate(&body, &key, &secret);
    let token = session["token"].as_str().unwrap();
    let result = a
        .as_token(
            token,
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":null}),
        )
        .unwrap();
    assert!(result["changes"].as_array().unwrap().is_empty());
    assert_eq!(
        a.as_token(
            token,
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":feed["cursor"]})
        )
        .unwrap_err()
        .status,
        409
    );
    assert_eq!(a.as_token(token,"/v1/offline/order-chunk",&json!({"protocol":FORMAT,"epoch":feed["epoch"],"order_id":first["order_id"],"revision":"1","section":"lines","offset":"0"})).unwrap_err().status,404);
}
#[test]
fn source_authorization_change_before_apply_preserves_original_without_booking() {
    let a = App::new("sales");
    let op = a.op(1);
    a.send(vec![op.clone()]).unwrap();
    a.f.c()
        .execute(
            "UPDATE automatic_devices SET enabled=0 WHERE id=?",
            [op["device_id"].as_str()],
        )
        .unwrap();
    a.advance();
    assert_eq!(a.state(&op), "rejected");
    assert_eq!(a.inventory()["counts"]["orders"], 0);
    assert_eq!(
        a.inventory()["offline_intake"]["counts"]["offline_operations"],
        1
    );
}
