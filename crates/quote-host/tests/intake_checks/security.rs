use super::support::*;
use quote_host::intake::{self, Intake};
use quote_ledger::store;
use serde_json::json;
#[test]
fn altered_digest_wrong_ledger_and_forged_owner_are_rejected() {
    let t = Test::new();
    let original = t.op(1);
    let mut v = original.clone();
    v["payload"]["details"]["order_ref"] = json!("tampered");
    assert_eq!(
        t.send(vec![v]).unwrap_err().code,
        "OFFLINE_CONTENT_DIGEST_CONFLICT"
    );
    let mut v = original.clone();
    v["ledger_id"] = json!(store::uid().unwrap());
    assert_eq!(
        t.send(vec![seal(v)]).unwrap_err().code,
        "OFFLINE_SITE_OR_DEVICE_CONFLICT"
    );
    let mut v = original;
    v["owner_id"] = json!(store::uid().unwrap());
    assert_eq!(t.send(vec![seal(v)]).unwrap_err().status, 403);
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn receipt_is_device_scoped_and_non_business_sessions_cannot_issue_lease() {
    let t = Test::new();
    let v = t.op(1);
    t.send(vec![v.clone()]).unwrap();
    let (p, key, _) = t.f.package("sales", &["quote", "orders", "edit_orders"], 2);
    let (data, secret) = t.f.candidate(&p);
    let session = t.f.activate(&data, &key, &secret);
    let other = Intake::open(&t.f.service).unwrap().unwrap();
    let r = other
        .handle(
            "POST",
            "/v1/offline/receipts",
            session["token"].as_str().unwrap(),
            &json!({"protocol":intake::FORMAT,"operation_ids":[v["operation_id"]]}),
        )
        .unwrap();
    assert_eq!(r["receipts"][0]["state"], "not_found");
    assert!(!r
        .to_string()
        .contains(v["content_sha256"].as_str().unwrap()));
    assert_eq!(
        other
            .handle(
                "POST",
                "/v1/offline/lease",
                &t.f.issuer_token,
                &json!({"protocol":intake::FORMAT,"request_id":store::uid().unwrap()})
            )
            .unwrap_err()
            .code,
        "OFFLINE_DEVICE_SESSION_REQUIRED"
    );
}
#[test]
fn revocation_after_receive_retains_original_and_stops_automatic_processing() {
    let t = Test::new();
    let v = t.op(1);
    t.send(vec![v.clone()]).unwrap();
    let raw: String = t
        .c()
        .query_row("SELECT operation_json FROM offline_operations", [], |r| {
            r.get(0)
        })
        .unwrap();
    t.f.c()
        .execute(
            "UPDATE automatic_devices SET enabled=0 WHERE id=?",
            [t.body["device_id"].as_str()],
        )
        .unwrap();
    t.intake.advance(&mut String::new()).unwrap();
    assert_eq!(
        t.c()
            .query_row("SELECT state FROM offline_states", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "rejected"
    );
    assert_eq!(
        t.c()
            .query_row("SELECT operation_json FROM offline_operations", [], |r| {
                r.get::<_, String>(0)
            })
            .unwrap(),
        raw
    );
    assert!(t.send(vec![v]).is_err());
}
#[test]
fn removed_edit_permission_is_preserved_as_rejected_business_candidate() {
    let t = Test::new();
    let parent = t.op(1);
    let child = edit(&t, &parent, 2);
    let c = t.f.c();
    let mut m: serde_json::Value = serde_json::from_str(
        &c.query_row(
            "SELECT manifest_json FROM package_grants WHERE id=?",
            [t.lease["body"]["package_id"].as_str()],
            |r| r.get::<_, String>(0),
        )
        .unwrap(),
    )
    .unwrap();
    m["capabilities"] = json!(["quote"]);
    c.execute(
        "UPDATE package_grants SET manifest_json=? WHERE id=?",
        rusqlite::params![store::encoded(&m), t.lease["body"]["package_id"].as_str()],
    )
    .unwrap();
    let r = t.send(vec![child]).unwrap();
    assert_eq!(r["receipts"][0]["state"], "rejected");
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
#[test]
fn batch_boundaries_fail_without_partial_originals() {
    let t = Test::new();
    let ops = (1..=33).map(|n| t.op(n)).collect();
    assert_eq!(t.send(ops).unwrap_err().status, 413);
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn lease_signature_retry_renewal_and_stream_rotation_are_stable() {
    use base64::{engine::general_purpose::STANDARD, Engine};
    use ring::signature::{UnparsedPublicKey, ED25519};
    let t = Test::new();
    let request = json!({"protocol":intake::FORMAT,"request_id":store::uid().unwrap()});
    let signed = t.call("/v1/offline/lease", &request).unwrap();
    assert_eq!(signed, t.call("/v1/offline/lease", &request).unwrap());
    assert_eq!(signed["body"]["stream_id"], t.lease["body"]["stream_id"]);
    let mut prices =
        serde_json::to_value(store::load_prices(&t.c(), "offline-fixture").unwrap()).unwrap();
    let actor = store::Actor {
        subject: t.body["device_id"].as_str().unwrap().into(),
        role: "sales".into(),
    };
    for cost in ["4", "99"] {
        prices["items"][0]["cost"] = json!(cost);
        let public =
            quote_host::protocol::catalog(serde_json::from_value(prices.clone()).unwrap(), &actor)
                .unwrap();
        assert_eq!(
            signed["body"]["price_sha256"],
            store::hash(intake::envelope::canonical(&public).unwrap())
        );
    }
    let mut input = format!("{}\n", intake::LEASE).into_bytes();
    input.extend(intake::envelope::canonical(&signed["body"]).unwrap());
    let public = STANDARD
        .decode(signed["public_key"].as_str().unwrap())
        .unwrap();
    let signature = STANDARD
        .decode(signed["signature"].as_str().unwrap())
        .unwrap();
    let key = UnparsedPublicKey::new(&ED25519, public);
    key.verify(&input, &signature).unwrap();
    input.push(b'!');
    assert!(key.verify(&input, &signature).is_err());
    let mut changed = request;
    changed["new_stream"] = json!(true);
    assert_eq!(
        t.call("/v1/offline/lease", &changed).unwrap_err().status,
        409
    );
    changed["request_id"] = json!(store::uid().unwrap());
    let rotated = t.call("/v1/offline/lease", &changed).unwrap();
    assert_ne!(rotated["body"]["stream_id"], t.lease["body"]["stream_id"]);
    let mut oversized = t.op(1);
    oversized["payload"]["details"]["customer"] = json!("x".repeat(262144));
    assert_eq!(t.send(vec![seal(oversized)]).unwrap_err().status, 413);
    assert_eq!(
        t.c()
            .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
