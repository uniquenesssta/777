use super::support::*;
use quote_host::intake::{self, Intake};
use quote_ledger::{integrity, store};
use serde_json::json;
#[test]
fn online_business_and_output_identities_cannot_be_reused_by_intake() {
    let mut t = Test::new();
    let operation = t.op(1);
    let request = json!({"request_id":operation["operation_id"],"snapshot":{"price_version_id":"offline-fixture","lines":[{"line_kind":"normal","product_id":"item","q":"1"}]},"details":{"customer":"online","order_ref":"online-1","wechat":""}});
    let saved =
        t.f.service
            .handle(
                "POST",
                "/v1/orders",
                &t.f.legacy_token,
                &request,
                "",
                "fixture",
            )
            .unwrap();
    assert_eq!(
        t.send(vec![operation]).unwrap_err().code,
        "OFFLINE_OPERATION_ID_CONFLICT"
    );
    let actor = t.f.service.auth.authenticate(&t.f.legacy_token).unwrap();
    let order =
        t.f.service
            .order(&actor, saved["order_id"].as_str().unwrap())
            .unwrap();
    let output_operation = t.op(2);
    t.f.service
        .outputs
        .as_ref()
        .unwrap()
        .enqueue(
            &actor,
            &json!({"request_id":output_operation["operation_id"],"kind":"excel_admin"}),
            order,
        )
        .unwrap();
    assert_eq!(
        t.send(vec![output_operation]).unwrap_err().code,
        "OFFLINE_OPERATION_ID_CONFLICT"
    );
    let accepted = t.op(3);
    t.send(vec![accepted.clone()]).unwrap();
    let mut retry = request;
    retry["request_id"] = accepted["operation_id"].clone();
    assert_eq!(
        t.f.service
            .handle(
                "POST",
                "/v1/orders",
                &t.f.legacy_token,
                &retry,
                "",
                "fixture"
            )
            .unwrap_err()
            .status,
        409
    );
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
#[test]
fn repeat_and_restart_keep_original_receipt_without_business_application() {
    let t = Test::new();
    let op = t.op(1);
    let first = t.send(vec![op.clone()]).unwrap();
    assert_eq!(first["receipts"][0]["state"], "received");
    assert_eq!(first["offline_orders"], false);
    assert_eq!(t.send(vec![op.clone()]).unwrap(), first);
    let restarted = Intake::open(&t.f.service).unwrap().unwrap();
    let found = restarted
        .handle(
            "POST",
            "/v1/offline/receipts",
            &t.token,
            &json!({"protocol":intake::FORMAT,"operation_ids":[op["operation_id"]]}),
        )
        .unwrap();
    assert_eq!(found["receipts"], first["receipts"]);
    let inventory = integrity::inventory(&t.c()).unwrap();
    assert_eq!(inventory["counts"]["orders"], 0);
    assert_eq!(
        inventory["offline_intake"]["counts"]["offline_operations"],
        1
    );
}
#[test]
fn changed_content_and_sequence_collision_preserve_first_and_rollback_batch() {
    let t = Test::new();
    let op = t.op(1);
    t.send(vec![op.clone()]).unwrap();
    let mut changed = op.clone();
    changed["payload"]["details"]["order_ref"] = json!("changed");
    let changed = seal(changed);
    let independent = t.op(2);
    assert_eq!(
        t.send(vec![independent.clone(), changed]).unwrap_err().code,
        "OFFLINE_OPERATION_ID_CONFLICT"
    );
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        t.receipts(vec![independent["operation_id"].clone()])["receipts"][0]["state"],
        "not_found"
    );
    assert!(t
        .c()
        .execute("UPDATE offline_operations SET operation_json='{}'", [])
        .is_err());
    assert!(
        t.c()
            .query_row("SELECT count(*) FROM offline_collisions", [], |r| r
                .get::<_, i64>(0))
            .unwrap()
            > 0
    );
    assert_eq!(
        t.send(vec![t.op(1)]).unwrap_err().code,
        "OFFLINE_OPERATION_ID_CONFLICT"
    );
}
#[test]
fn out_of_order_chain_waits_while_independent_order_is_received() {
    let t = Test::new();
    let parent = t.op(1);
    let child = edit(&t, &parent, 3);
    let unrelated = t.op(2);
    let r = t
        .send(vec![child.clone(), unrelated, parent.clone()])
        .unwrap();
    assert_eq!(r["receipts"][0]["state"], "waiting_dependency");
    assert_eq!(r["receipts"][1]["state"], "received");
    assert_eq!(r["receipts"][2]["state"], "received");
    let mut cursor = String::new();
    t.intake.advance(&mut cursor).unwrap();
    assert_eq!(
        t.receipts(vec![child["operation_id"].clone()])["receipts"][0]["state"],
        "waiting_dependency"
    );
    let mut rejected = t.op(4);
    rejected["rule_version"] = json!("business-old");
    let rejected = seal(rejected);
    let dependent = edit(&t, &rejected, 5);
    let result = t.send(vec![rejected, dependent]).unwrap();
    assert_eq!(result["receipts"][0]["state"], "rejected");
    assert_eq!(result["receipts"][1]["state"], "rejected");
}
#[test]
fn cycles_and_cross_order_dependencies_are_not_partially_received() {
    let t = Test::new();
    let a = t.op(1);
    let mut b = edit(&t, &a, 2);
    b["order_id"] = json!(store::uid().unwrap());
    let b = seal(b);
    assert_eq!(
        t.send(vec![a.clone(), b]).unwrap_err().code,
        "OFFLINE_DEPENDENCY_BINDING_CONFLICT"
    );
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    let mut a = edit(&t, &a, 1);
    a["base"]["previous_operation_id"] = a["operation_id"].clone();
    let a = seal(a);
    assert_eq!(
        t.send(vec![a]).unwrap_err().code,
        "OFFLINE_DEPENDENCY_CYCLE"
    );
}
#[test]
fn canonical_matches_frozen_unicode_vector_and_rejects_wire_numbers() {
    let fixtures: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../docs/contracts/P08-02-3/examples.json"
    ))
    .unwrap();
    for v in fixtures["operations"].as_array().unwrap() {
        intake::envelope::validate(v).unwrap();
        assert_eq!(intake::envelope::digest(v).unwrap(), v["content_sha256"]);
    }
    assert!(intake::envelope::canonical(&json!({"amount":1.2})).is_err());
}
