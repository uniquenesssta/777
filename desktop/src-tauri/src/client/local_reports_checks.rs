use super::*;
#[test]
fn large_local_report_splits_without_dropping_or_duplicating_orders() {
    let db = Sqlite::open_in_memory().unwrap();
    db.execute_batch("CREATE TABLE parts(data TEXT)").unwrap();
    let orders=(0..240).map(|n|json!({"order_id":format!("order-{n}"),"created_at":if n<120{"2026-09-20T00:00:00Z"}else{"2026-10-20T00:00:00Z"},"state":"active","details":{"customer":"测试客户","order_ref":format!("order-{n}"),"wechat":"wx"},"income_cents":"1000","cost_cents":"400","profit_cents":"600","lines":[],"notes":[{"body":"a".repeat(4000)},{"body":"b".repeat(4000)},{"body":"c".repeat(3000)}]})).collect();
    stage(&db, orders, "2026-09-01", "2026-10-31", "batch").unwrap();
    let chunks = db
        .prepare("SELECT data FROM parts ORDER BY rowid")
        .unwrap()
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<std::result::Result<Vec<_>, _>>()
        .unwrap();
    assert!(chunks.len() > 1);
    let mut ids = std::collections::HashSet::new();
    for raw in chunks {
        let orders: Vec<Value> = serde_json::from_str(&raw).unwrap();
        let bytes =
            quote_excel::write::write(&part(&orders, "2026-09-01", "2026-10-31", "batch")).unwrap();
        assert!(bytes.len() < quote_excel::OUTPUT_LIMIT);
        for order in orders {
            assert!(ids.insert(order["order_id"].as_str().unwrap().to_owned()));
        }
    }
    assert_eq!(ids.len(), 240);
}
