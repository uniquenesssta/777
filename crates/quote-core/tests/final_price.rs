use quote_core::{
    calculation::calculate,
    models::{Prices, Quote},
    session::{Details, OutputKind, PriceSource, Session},
};
use serde_json::json;
fn fixtures() -> (Quote, Prices) {
    (serde_json::from_value(json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":"2"},{"kind":"discount","percent":"50%"}]})).unwrap(),
    serde_json::from_value(json!({"price_version_id":"v1","items":[{"product_id":"P","sale":"100","cost":"40","single":true}]})).unwrap())
}
#[test]
fn final_price_applies_once_after_discounts_and_preserves_line_prices_and_costs() {
    let (mut q, p) = fixtures();
    let auto = calculate(&q, &p);
    assert_eq!(auto.totals.as_ref().unwrap().income(), 10000);
    q.final_price = Some("90.25".into());
    let agreed = calculate(&q, &p);
    let total = agreed.totals.as_ref().unwrap();
    assert_eq!(
        (total.income(), total.cost(), total.profit()),
        (9025, 8000, 1025)
    );
    assert_eq!(agreed.wire()["lines"], auto.wire()["lines"]);
    q.final_price = Some("0".into());
    assert_eq!(calculate(&q, &p).totals.unwrap().profit(), -8000);
    q.final_price = Some(" ".into());
    assert_eq!(calculate(&q, &p).totals.unwrap().income(), 10000);
}
#[test]
fn invalid_price_never_produces_an_order_total() {
    let (mut q, p) = fixtures();
    for raw in [
        "-1",
        "1.001",
        "NaN",
        "1e2",
        "1/2",
        "1,000",
        "92233720368547758.08",
    ] {
        q.final_price = Some(raw.into());
        let r = calculate(&q, &p);
        assert!(r.totals.is_none(), "{raw}");
        assert!(r.wire().to_string().contains("FINAL_PRICE_INVALID"));
    }
    assert_eq!(
        quote_core::settlement::cents("92233720368547758.07").unwrap(),
        Some(i64::MAX)
    );
}
#[test]
fn confirmed_session_allows_an_agreed_total_different_from_line_sum() {
    let (mut q, p) = fixtures();
    q.final_price = Some("90.25".into());
    let mut s = Session::new(
        "5d782c12-60bd-421a-9f12-a3e9fe819d03".into(),
        Some(q),
        Some(p),
        Details::default(),
        PriceSource::Current,
        Some("v1".into()),
    )
    .unwrap();
    s.calculate();
    assert_eq!(s.prepare_output(OutputKind::Excel).status, "ok");
}
