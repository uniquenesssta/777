use super::support::*;
use quote_host::{
    cluster::{config, snapshot},
    intake, recovery,
};
use quote_ledger::{integrity, store};
use serde_json::json;
#[test]
fn schema_three_backup_restores_received_operations_and_has_no_signing_secret() {
    let t = Test::new();
    t.send(vec![t.op(1)]).unwrap();
    let data = recovery::capture_live(&t.f.service, "2026-10-19").unwrap();
    assert_eq!(data.format, recovery::FORMAT_V3);
    let excel = quote_excel::backup::write(&serde_json::to_value(&data).unwrap()).unwrap();
    assert!(excel.starts_with(b"PK"));
    let encoded = recovery::encode(&data).unwrap();
    assert!(!String::from_utf8_lossy(&encoded).contains(&t.f.issuer_secret));
    assert!(!String::from_utf8_lossy(&encoded).contains("offline-signing.pk8"));
    let decoded = recovery::decode(&encoded).unwrap();
    let target = t.f.root.join("restored.sqlite3");
    recovery::restore_ledger(&decoded, &target).unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&target, false).unwrap()).unwrap(),
        decoded.inventory
    );
    assert!(!t.f.root.join("offline-signing.pk8").exists());
}
#[test]
fn snapshot_generation_changes_for_intake_without_a_new_business_revision() {
    let t = Test::new();
    t.f.cluster();
    let cfg = config::required(&t.f.root).unwrap();
    let first = snapshot::capture(&t.f.service, &cfg).unwrap().unwrap();
    let before = store::verify(&t.c()).unwrap()["revision"].clone();
    t.send(vec![t.op(1)]).unwrap();
    let second = snapshot::capture(&t.f.service, &cfg).unwrap().unwrap();
    assert!(second.generation > first.generation);
    assert_eq!(store::verify(&t.c()).unwrap()["revision"], before);
    let m = snapshot::read(&t.f.root, &second).unwrap();
    assert_eq!(m.format, snapshot::FORMAT_V3);
    assert_eq!(
        m.inventory["offline_intake"]["counts"]["offline_operations"],
        1
    );
    let mut old = m.clone();
    old.format = snapshot::FORMAT_V2.into();
    assert!(snapshot::validate_data(&snapshot::folder(&t.f.root, &second).unwrap(), &old).is_err());
}
#[test]
fn explicit_upgrade_preserves_existing_order_and_legacy_schema_default() {
    let f = crate::automatic_support::Fixture::new();
    let actor = f.service.auth.authenticate(&f.legacy_token).unwrap();
    let mut c = store::open(&f.service.ledger, true).unwrap();
    let prices=serde_json::from_value(json!({"price_version_id":"before-offline","items":[{"product_id":"item","sale":"10","cost":"4","k":"1","single":true}]})).unwrap();
    store::mutate(
        &mut c,
        store::Mutation::PublishPrices {
            request_id: store::uid().unwrap(),
            actor: actor.clone(),
            prices,
            expected_price_version_id: None,
        },
        None,
    )
    .unwrap();
    let receipt=store::mutate(&mut c,store::Mutation::SubmitOrder{request_id:store::uid().unwrap(),actor:actor.clone(),snapshot:serde_json::from_value(json!({"price_version_id":"before-offline","lines":[{"kind":"normal","product_id":"item","q":"2"}]})).unwrap(),details:json!({"customer":"before","order_ref":"old-01","wechat":""})},None).unwrap();
    assert_eq!(store::verify(&c).unwrap()["schema_version"], 2);
    let before = f
        .service
        .order(&actor, receipt["order_id"].as_str().unwrap())
        .unwrap();
    let output = f
        .service
        .outputs
        .as_ref()
        .unwrap()
        .enqueue(
            &actor,
            &json!({"request_id":store::uid().unwrap(),"kind":"excel_admin"}),
            before.clone(),
        )
        .unwrap();
    intake::setup::provision(&f.service).unwrap();
    assert_eq!(store::verify(&c).unwrap()["schema_version"], 3);
    assert_eq!(
        f.service
            .order(&actor, receipt["order_id"].as_str().unwrap())
            .unwrap(),
        before
    );
    assert_eq!(
        store::query_request(&c, receipt["request_id"].as_str().unwrap(), &actor).unwrap(),
        receipt
    );
    assert!(f
        .root
        .join("private/ledger-before-offline.sqlite3")
        .is_file());
    f.service
        .outputs
        .as_ref()
        .unwrap()
        .validate_ledger(&f.service.ledger)
        .unwrap();
    assert_eq!(
        f.service
            .outputs
            .as_ref()
            .unwrap()
            .receipt(&actor, output["request_id"].as_str().unwrap(), None)
            .unwrap(),
        Some(output)
    );
}
