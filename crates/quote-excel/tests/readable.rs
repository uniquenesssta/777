use serde_json::{json, Value};
fn order(date: &str, id: &str, income: &str, cost: &str, profit: &str, state: &str) -> Value {
    json!({"order_id":id,"created_at":date,"updated_at":date,"state":state,"details":{"customer":"=淘宝001","order_ref":"00012345678901234567890","wechat":"wx0001"},"income_cents":income,"cost_cents":cost,"profit_cents":profit,"lines":[{"raw":{"line_kind":"normal","product_id":"单件"},"normalized":{"q":"1","sale":"10","k":"1"},"income_cents":income}],"notes":[{"body":"测试备注","created_at":date}]})
}
#[test]
fn months_use_beijing_days_and_totals_exclude_voids_without_losing_ids() {
    let orders = vec![
        order("2026-09-30T15:59:59Z", "a", "1000", "400", "600", "active"),
        order(
            "2026-09-30T16:00:00Z",
            "b",
            "2000",
            "2500",
            "-500",
            "active",
        ),
        order("2026-10-02T00:00:00Z", "c", "3000", "1000", "2000", "void"),
    ];
    let payload = json!({"format":"777-output-v1","presentation":"monthly-v1","job_id":"test","kind":"excel_period","orders":orders,"range":{"from":"2026-09-01","to":"2026-10-31"}});
    let bytes = quote_excel::write::write(&payload).unwrap();
    let book = quote_excel::read::read(&bytes).unwrap();
    assert_eq!(
        book.sheets
            .iter()
            .map(|s| s.name.as_str())
            .collect::<Vec<_>>(),
        vec!["阅读说明", "2026年09月", "2026年10月", "Protocol"]
    );
    for (name, want) in [("2026年09月", "10.00"), ("2026年10月", "20.00")] {
        let s = book.sheets.iter().find(|s| s.name == name).unwrap();
        let row = s
            .cells
            .iter()
            .find(|c| c.value.as_deref() == Some("本月有效订单合计"))
            .unwrap()
            .row;
        assert!(s
            .cells
            .iter()
            .any(|c| c.row == row && c.column == 14 && c.value.as_deref() == Some(want)));
        assert!(s
            .cells
            .iter()
            .any(|c| c.value.as_deref() == Some("00012345678901234567890")));
        assert!(s
            .cells
            .iter()
            .any(|c| c.value.as_deref() == Some("=淘宝001") && c.kind == "s"));
    }
    let october = book.sheets.iter().find(|s| s.name == "2026年10月").unwrap();
    assert!(october
        .cells
        .iter()
        .any(|c| c.value.as_deref() == Some("-5.00")));
    assert!(october
        .cells
        .iter()
        .any(|c| c.value.as_deref() == Some("已作废")));
}
