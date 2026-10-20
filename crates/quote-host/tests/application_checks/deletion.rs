use super::support::*;
use quote_host::intake::FORMAT;
use quote_ledger::{deletion, store};
use serde_json::json;
#[test]
fn deleted_order_emits_feed_and_offline_edits_cannot_restore_it() {
    let mut a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let before = a.order(&first);
    let actor = a.f.service.auth.authenticate(&a.f.legacy_token).unwrap();
    deletion::delete(
        &mut store::open(&a.f.service.ledger, true).unwrap(),
        &actor,
        &store::uid().unwrap(),
        first["order_id"].as_str().unwrap(),
        1,
        "test cleanup",
    )
    .unwrap();
    let changed = edit(
        &a,
        &first,
        2,
        1,
        json!({"wechat":"offline change"}),
        json!([]),
    );
    a.send(vec![changed.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&changed), "conflict");
    let reason: String = a
        .c()
        .query_row(
            "SELECT reason FROM offline_states WHERE operation_id=?",
            [changed["operation_id"].as_str()],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(reason, "ORDER_DELETED");
    let mut restore = a.op(3);
    restore["kind"] = json!("set_state");
    restore["order_id"] = first["order_id"].clone();
    restore["base"] = json!({"order_revision":"2","previous_operation_id":null});
    restore["payload"] = json!({"state":"active","reason":"offline restore"});
    let restore = seal(restore);
    a.send(vec![restore.clone()]).unwrap();
    a.advance();
    assert_ne!(a.state(&restore), "applied");
    assert_eq!(a.inventory()["active_income_cents"], "0");
    let feed = a
        .call(
            "/v1/offline/changes",
            &json!({"protocol":FORMAT,"cursor":null}),
        )
        .unwrap();
    assert!(feed["changes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v["order_id"] == first["order_id"] && v["order_revision"] == "2"));
    let chunk=a.call("/v1/offline/order-chunk",&json!({"protocol":FORMAT,"epoch":feed["epoch"],"order_id":first["order_id"],"revision":"2","section":"lines","offset":"0"})).unwrap();
    assert_eq!(chunk["order"]["deleted"], true);
    assert_eq!(chunk["order"]["state"], "void");
    assert_eq!(chunk["items"][0]["line_id"], before["lines"][0]["line_id"]);
    a.f.cluster();
    let config = quote_host::cluster::config::required(&a.f.root).unwrap();
    let reference = quote_host::cluster::snapshot::capture(&a.f.service, &config)
        .unwrap()
        .unwrap();
    let manifest = quote_host::cluster::snapshot::read(&a.f.root, &reference).unwrap();
    let folder = quote_host::cluster::snapshot::folder(&a.f.root, &reference).unwrap();
    quote_host::cluster::snapshot::validate_data(&folder, &manifest).unwrap();
    assert_eq!(manifest.inventory, a.inventory());
    // Packaged manager/sales credentials cannot invoke developer deletion even with all business capabilities.
    let token = a.token.clone();
    let result = a.t.f.service.handle(
        "POST",
        "/v1/developer/orders/delete",
        &token,
        &json!({}),
        "",
        "test",
    );
    assert!(result.is_err());
}
