use super::support::*;
use quote_host::{files, intake::FORMAT};
use quote_ledger::store;
use serde_json::json;
fn conflicted(a: &App) -> (serde_json::Value, serde_json::Value) {
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let one = edit(
        a,
        &first,
        2,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "2")]),
    );
    a.send(vec![one]).unwrap();
    a.advance();
    let bad = edit(
        a,
        &first,
        3,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "3")]),
    );
    a.send(vec![bad.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&bad), "conflict");
    (first, bad)
}
#[test]
fn normal_manager_sales_and_issuer_sessions_have_no_resolution_authority() {
    let a = App::new("manager");
    let (_, bad) = conflicted(&a);
    let input = decision(&bad, 2, "apply_candidate");
    for token in [&a.f.legacy_token, &a.token, &a.f.issuer_token] {
        assert!(a
            .intake
            .handle("POST", "/v1/offline/resolve", token, &input)
            .is_err());
    }
    a.grant();
    assert!(a
        .intake
        .handle("POST", "/v1/offline/resolve", &a.token, &input)
        .is_err());
    let listing = a
        .review(
            "/v1/offline/review",
            &json!({"protocol":FORMAT,"after":null}),
        )
        .unwrap();
    assert_eq!(
        listing["items"][0]["operation"]["operation_id"],
        bad["operation_id"]
    );
}
#[test]
fn decision_keeps_original_three_way_evidence_and_is_idempotent() {
    let a = App::new("manager");
    let (first, bad) = conflicted(&a);
    a.grant();
    let input = decision(&bad, 2, "apply_candidate");
    let raw: String = a
        .c()
        .query_row(
            "SELECT operation_json FROM offline_operations WHERE operation_id=?",
            [bad["operation_id"].as_str()],
            |r| r.get(0),
        )
        .unwrap();
    let result = a.review("/v1/offline/resolve", &input).unwrap();
    assert_eq!(result["revision"], 3);
    assert_eq!(a.order(&first)["income_cents"], "3000");
    assert_eq!(a.state(&bad), "conflict");
    let before = a.inventory();
    assert_eq!(a.review("/v1/offline/resolve", &input).unwrap(), result);
    assert_eq!(a.inventory(), before);
    let mut reused = input.clone();
    reused["decision"] = json!("keep_current");
    assert!(a.review("/v1/offline/resolve", &reused).is_err());
    assert!(a
        .review("/v1/offline/resolve", &decision(&bad, 3, "keep_current"))
        .is_err());
    let after: String = a
        .c()
        .query_row(
            "SELECT operation_json FROM offline_operations WHERE operation_id=?",
            [bad["operation_id"].as_str()],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(after, raw);
    let history = a.order(&first)["history"].as_array().unwrap().clone();
    assert_eq!(history.len(), 2);
    let receipt = a.receipts(vec![bad["operation_id"].clone()]);
    assert_eq!(receipt["receipts"][0]["resolution"], "applied");
    assert!(receipt["receipts"][0]["result"].get("cost_cents").is_none());
    let chunk=a.review("/v1/offline/review-chunk",&json!({"protocol":FORMAT,"operation_id":bad["operation_id"],"section":"base","offset":"0"})).unwrap();
    assert!(chunk["data_base64"].is_string());
    assert!(chunk["sha256"].is_string());
}
#[test]
fn stale_decision_requires_recheck_and_keep_does_not_double_book() {
    let a = App::new("manager");
    let (first, bad) = conflicted(&a);
    a.grant();
    assert_eq!(
        a.review("/v1/offline/resolve", &decision(&bad, 1, "apply_candidate"))
            .unwrap_err()
            .code,
        "RESOLUTION_VERSION_CONFLICT"
    );
    let result = a
        .review("/v1/offline/resolve", &decision(&bad, 2, "keep_current"))
        .unwrap();
    assert_eq!(result["decision"], "keep_current");
    assert_eq!(a.order(&first)["income_cents"], "2000");
    assert_eq!(a.inventory()["counts"]["orders"], 1);
}
#[test]
fn duplicate_candidate_can_be_explicitly_merged_into_same_owner_order() {
    let a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let mut duplicate = a.op(2);
    duplicate["payload"]["details"]["order_ref"] = first["payload"]["details"]["order_ref"].clone();
    let duplicate = seal(duplicate);
    a.send(vec![duplicate.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&duplicate), "conflict");
    a.grant();
    let mut input = decision(&duplicate, 1, "merge_into");
    input["target_order_id"] = first["order_id"].clone();
    let result = a.review("/v1/offline/resolve", &input).unwrap();
    assert_eq!(result["order_id"], first["order_id"]);
    assert_eq!(a.inventory()["counts"]["orders"], 1);
    assert_eq!(a.order(&first)["income_cents"], "2000");
    assert_eq!(
        a.receipts(vec![duplicate["operation_id"].clone()])["receipts"][0]["resolution"],
        "merged"
    );
}
#[test]
fn reviewer_grants_are_epoch_bound_and_are_not_inferred_from_admin_role() {
    let a = App::new("manager");
    a.grant();
    let path = a.f.root.join("private/offline-reviewers.json");
    let mut grants = files::read_json(&path).unwrap();
    grants["epoch"] = json!(store::uid().unwrap());
    files::replace_json(&path, &grants).unwrap();
    assert_eq!(
        a.review(
            "/v1/offline/review",
            &json!({"protocol":FORMAT,"after":null})
        )
        .unwrap_err()
        .status,
        403
    );
}
