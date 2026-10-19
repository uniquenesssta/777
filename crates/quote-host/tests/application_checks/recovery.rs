use super::support::*;
use quote_host::{
    cluster::{config, snapshot},
    recovery,
};
use quote_ledger::{integrity, store};
use serde_json::json;
#[test]
fn applied_conflict_and_resolution_rows_survive_v3_restore_and_replication() {
    let a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let one = edit(
        &a,
        &first,
        2,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "2")]),
    );
    a.send(vec![one]).unwrap();
    a.advance();
    let two = edit(
        &a,
        &first,
        3,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "3")]),
    );
    a.send(vec![two.clone()]).unwrap();
    a.advance();
    a.grant();
    a.review("/v1/offline/resolve", &decision(&two, 2, "apply_candidate"))
        .unwrap();
    let expected = a.inventory();
    let data = recovery::capture_live(&a.f.service, "2026-10-20").unwrap();
    let raw = recovery::encode(&data).unwrap();
    let data = recovery::decode(&raw).unwrap();
    let restored = a.f.root.join("restore-c.sqlite3");
    recovery::restore_ledger(&data, &restored).unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&restored, false).unwrap()).unwrap(),
        expected
    );
    assert!(!String::from_utf8_lossy(&raw).contains("offline-reviewers.json"));
    a.f.cluster();
    let cfg = config::required(&a.f.root).unwrap();
    let reference = snapshot::capture(&a.f.service, &cfg).unwrap().unwrap();
    let manifest = snapshot::read(&a.f.root, &reference).unwrap();
    snapshot::validate_data(&snapshot::folder(&a.f.root, &reference).unwrap(), &manifest).unwrap();
    assert_eq!(manifest.inventory, expected);
    let book = quote_excel::backup::write(&serde_json::to_value(&data).unwrap()).unwrap();
    assert!(book.starts_with(b"PK"));
}
#[test]
fn forged_applied_identity_and_resolution_metadata_fail_inventory() {
    let a = App::new("manager");
    let op = a.op(1);
    a.send(vec![op.clone()]).unwrap();
    a.advance();
    let c = a.c();
    c.execute("UPDATE offline_states SET applied_request_id=(SELECT request_id FROM requests WHERE operation='publish_prices') WHERE operation_id=?",[op["operation_id"].as_str()]).unwrap();
    assert!(integrity::inventory(&c).is_err());
}
