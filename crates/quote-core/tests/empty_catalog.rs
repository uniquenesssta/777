use quote_core::configuration::{parse_config, Source};
use serde_json::json;

#[test]
fn explicit_empty_catalog_retains_version_and_validation() {
    let parsed = parse_config(Source::Text(r#"{"items":[]}"#), &json!("empty-v1"), None);
    assert_eq!(parsed.status, "ok");
    let prices = parsed.config.unwrap().prices;
    assert_eq!(prices.price_version_id, "empty-v1");
    assert!(prices.items.is_empty());
    for raw in [
        r#"{}"#,
        r#"{"export_dir":""}"#,
        r#"{"items":null}"#,
        r#"{"items":[],"unexpected":true}"#,
        r#"{"items":[{}]}"#,
    ] {
        assert!(parse_config(Source::Text(raw), &json!("v1"), None)
            .config
            .is_none());
    }
}
