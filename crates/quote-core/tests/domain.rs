use num_bigint::BigInt;
use quote_core::{
    calculation::calculate,
    configuration::{parse_config, Source},
    models::*,
    numbers::{parse_number, rounded_ratio, Decimal},
    session::*,
};
use serde_json::json;
fn q(quantity: &str) -> Quote {
    serde_json::from_value(
        json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":quantity}]}),
    )
    .unwrap()
}
fn p() -> Prices {
    serde_json::from_value(json!({"price_version_id":"v1","items":[{"product_id":"P","sale":"10","cost":"4","single":true}]})).unwrap()
}
fn session() -> Session {
    Session::new(
        "5d782c12-60bd-421a-9f12-a3e9fe819d03".into(),
        Some(q("1")),
        Some(p()),
        Details::default(),
        PriceSource::Current,
        Some("v1".into()),
    )
    .unwrap()
}
#[test]
fn division_rounds_each_operator() {
    assert_eq!(
        parse_number(&json!("1/3*3"), "q", false).unwrap().text(),
        "0.999999999999"
    );
}
#[test]
fn negative_half_ties_and_exact_remainder() {
    assert_eq!(
        rounded_ratio((-3).into(), 2.into(), 0).unwrap(),
        BigInt::from(-2)
    );
    assert_eq!(
        parse_number(&json!("(5)%(0-3)+3"), "q", false)
            .unwrap()
            .text(),
        "2"
    );
    assert_eq!(Decimal::new((-5).into(), 3).settle().unwrap(), -1);
}
#[test]
fn intermediate_capacity_checked_before_cancellation() {
    assert_eq!(
        parse_number(&json!("(1e9*1e9*1e9*1e9*1e9*1e9)%3"), "q", false)
            .unwrap_err()
            .reason,
        "INTERMEDIATE_CAPACITY"
    );
    assert_eq!(
        parse_number(&json!("(1e9*1e9*1e9*1e9*1e9)%3"), "q", false)
            .unwrap()
            .text(),
        "1"
    );
}
#[test]
fn field_and_ast_limits_are_not_rounded_away() {
    for (raw, reason) in [
        ("0.0000000000001", "LITERAL_CAPACITY"),
        ("0.000001*0.0000001", "FIELD_SCALE"),
        ("-1", "FIELD_RANGE"),
        ("1/0", "DIVISION_BY_ZERO"),
        ("True", "LITERAL"),
        ("2**2", "UNSUPPORTED_NODE"),
    ] {
        assert_eq!(
            parse_number(&json!(raw), "q", false).unwrap_err().reason,
            reason
        );
    }
    assert_eq!(
        parse_number(&json!("-".repeat(18) + "1"), "q", false)
            .unwrap_err()
            .reason,
        "AST_DEPTH"
    );
    assert_eq!(
        parse_number(&json!("1+".repeat(21) + "1"), "q", false)
            .unwrap_err()
            .reason,
        "AST_CAPACITY"
    );
}
#[test]
fn money_capacity_checks_profit_and_symmetric_limit() {
    assert!(Amounts::new(i64::MAX, 0, false).is_ok());
    assert!(Amounts::new(-i64::MAX, 0, false).is_ok());
    assert!(Amounts::new(i64::MIN, 0, false).is_err());
    assert!(Amounts::new(-i64::MAX, i64::MAX, false).is_err());
    let a = Amounts::new(1, i64::MAX, false).unwrap();
    assert!(a.display()["margin"]
        .as_str()
        .unwrap()
        .starts_with("-922337203685477580600.0"));
}
#[test]
fn wire_cents_are_strings_above_javascript_integer_limit() {
    let a = Amounts::new(i64::MAX, 0, false).unwrap();
    assert_eq!(a.cents()["income_cents"], "9223372036854775807");
    assert_eq!(a.display()["income"], "92233720368547758.07");
}
#[test]
fn second_line_failure_has_no_partial_results() {
    let mut q = q("1");
    q.lines.push(Line::Normal {
        product_id: json!("P"),
        q: json!("1/0"),
        h: json!(""),
        w: json!(""),
        name: json!(""),
    });
    let r = calculate(&q, &p());
    assert_eq!(r.issues[0].line_index, Some(2));
    assert!(r.lines.is_none());
    assert!(r.totals.is_none());
}
#[test]
fn config_numeric_tokens_bom_and_invalid_surrogate() {
    let raw="\u{feff}{\r\n\"items\":[{\"name\":\"中文\",\"sale\":999999999.999999999999,\"cost\":0.123456789012,\"single\":true}]}";
    let r = parse_config(Source::Bytes(raw.as_bytes()), &json!("v1"), None);
    let c = r.config.unwrap();
    assert_eq!(c.original_json, raw);
    assert_eq!(c.prices.items[0].sale, "999999999.999999999999");
    let bad = parse_config(
        Source::Text(r#"{"items":[{"name":"\ud800","sale":1,"cost":0}]}"#),
        &json!("v1"),
        None,
    );
    assert_eq!(bad.issues[0].reason, "CONFIG_TEXT_ENCODING");
}
#[test]
fn duplicate_keys_and_boolean_flags_block_whole_candidate() {
    for (raw, reason) in [
        (r#"{"items":[],"items":[]}"#, "JSON_DUPLICATE_KEY"),
        (
            r#"{"items":[{"name":"P","sale":1,"cost":0,"single":"false"}]}"#,
            "SINGLE_NOT_BOOLEAN",
        ),
    ] {
        let r = parse_config(Source::Text(raw), &json!("v1"), None);
        assert!(r.config.is_none());
        assert_eq!(r.issues[0].reason, reason);
    }
}
#[test]
fn old_and_same_identity_other_generation_completions_are_discarded() {
    let mut s = session();
    let old = s.begin_calculation();
    s.update_inputs(q("2"), None).unwrap();
    s.calculate();
    assert!(!s.apply_calculation(run_calculation(old.clone())));
    let other = session();
    assert!(!s.apply_calculation(run_calculation(other.begin_calculation())));
    s.update_inputs(q("1"), None).unwrap();
    assert!(!s.apply_calculation(run_calculation(old)));
}
#[test]
fn blocked_dispatch_calls_zero_and_all_outputs_freeze_same_cents() {
    let mut s = session();
    for kind in [
        OutputKind::Excel,
        OutputKind::QuoteImage,
        OutputKind::Screenshot,
    ] {
        assert!(s
            .dispatch_output(kind, |_| panic!("blocked writer invoked"))
            .is_err());
    }
    s.calculate();
    let a = s.dispatch_output(OutputKind::Excel, Payload::wire).unwrap();
    for kind in [OutputKind::QuoteImage, OutputKind::Screenshot] {
        assert_eq!(s.dispatch_output(kind, Payload::wire).unwrap(), a);
    }
    s.invalidate_inputs(vec![]).unwrap();
    assert!(s
        .dispatch_output(OutputKind::Excel, |_| panic!("cached capability"))
        .is_err());
    assert_eq!(a["revision"], "0");
}
#[test]
fn price_refresh_requires_current_recalculation_and_confirmation() {
    let mut s = session();
    s.calculate();
    s.observe_source(PriceSource::Current, Some("v2".into()))
        .unwrap();
    assert_eq!(s.prepare_output(OutputKind::Excel).status, "PRICE_STALE");
    let mut p = p();
    p.price_version_id = json!("v2");
    s.refresh_prices(p).unwrap();
    assert!(!s.confirm_prices(s.revision()));
    s.calculate();
    assert_eq!(
        s.prepare_output(OutputKind::Excel).issues[0].reason,
        "PRICE_CONFIRMATION_REQUIRED"
    );
    assert!(!s.confirm_prices(0));
    assert!(s.confirm_prices(s.revision()));
    assert_eq!(s.prepare_output(OutputKind::Excel).status, "ok");
}
#[test]
fn writer_errors_propagate_without_invalidating_result() {
    let mut s = session();
    s.calculate();
    assert_eq!(
        s.dispatch_output(OutputKind::Excel, |_| Err::<(), _>("I/O failed"))
            .unwrap(),
        Err("I/O failed")
    );
    assert_eq!(s.state_wire()["status"], "valid");
}
#[test]
fn unavailable_prices_only_allow_draft_preview() {
    let mut s = session();
    s.observe_source(PriceSource::Unavailable, Some("v1".into()))
        .unwrap();
    s.calculate();
    assert_eq!(s.state_wire()["status"], "valid");
    assert_eq!(s.prepare_output(OutputKind::Excel).status, "IO_UNAVAILABLE");
}
#[test]
fn malformed_model_cannot_become_formal_result() {
    let mut p = p();
    p.items[0].k = json!({"widget":"mutable"});
    let r = calculate(&q("1"), &p);
    assert_eq!(r.issues[0].reason, "SNAPSHOT_SCALAR_TYPE");
    assert!(r.totals.is_none());
}

#[test]
fn unicode_discount_digits_match_python_decimal() {
    for raw in ["９０％", "٩٠%", "𝟡𝟘%"] {
        assert_eq!(
            quote_core::numbers::parse_percent(&json!(raw))
                .unwrap()
                .text(),
            "90"
        );
    }
}
