use super::*;
#[test]
fn authorized_finance_uses_real_cached_cost_plus_prices_and_losing_finance_scrubs_views() {
    let f = Fixture::with_finance(true);
    let mut body = f.body();
    body["snapshot"]["lines"][0]["q"] = json!("3");
    let saved = f.local.save("save", &body).unwrap();
    let id = saved["order_id"].as_str().unwrap();
    let view = f.local.order(id).unwrap();
    assert_eq!(view["income_cents"], "3000");
    assert_eq!(view["cost_cents"], "1200");
    assert_eq!(view["profit_cents"], "1800");
    let mut context = f.local.context().unwrap();
    context["lease"]["body"]["capabilities"] = json!(["edit_orders", "orders", "quote"]);
    f.local.transaction(|| f.local.narrow(&context)).unwrap();
    let raw: Vec<u8> = f
        .local
        .c
        .query_row("SELECT working FROM local_orders WHERE id=?", [id], |r| {
            r.get(0)
        })
        .unwrap();
    let narrow = f.local.decode(&raw).unwrap();
    assert!(narrow.get("cost_cents").is_none());
    assert!(narrow["lines"][0].get("profit_cents").is_none());
    assert_eq!(
        f.local
            .c
            .query_row("SELECT count(*) FROM local_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
#[test]
fn history_is_published_only_after_all_fragment_bytes_match_the_complete_digest() {
    let f = Fixture::new();
    let saved = f.local.save("save", &f.body()).unwrap();
    let id = saved["order_id"].as_str().unwrap();
    let data=serde_json::to_vec(&json!({"revision":"1","to_revision":"2","created_at":"synthetic","changes":[{"section":"订单","field":"金额","before":"1000","after":"2000","format":"money"}]})).unwrap();
    let sha = quote_ledger::store::hash(&data);
    let split = 23;
    f.local.history_part(id,"1",&json!({"offset":"0","sha256":sha,"total_bytes":data.len().to_string(),"data_base64":STANDARD.encode(&data[..split]),"next_offset":split.to_string()})).unwrap();
    assert!(f.local.meta(&format!("diff:{id}:1")).unwrap().is_none());
    f.local.history_part(id,"1",&json!({"offset":split.to_string(),"sha256":sha,"total_bytes":data.len().to_string(),"data_base64":STANDARD.encode(&data[split..]),"next_offset":null})).unwrap();
    assert_eq!(
        f.local.changes(id, "1").unwrap()["changes"][0]["after"],
        "2000"
    );
}
