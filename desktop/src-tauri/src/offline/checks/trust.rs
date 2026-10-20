use super::*;
#[test]
fn forged_signature_catalog_or_binding_cannot_authorize_local_writes() {
    let f = Fixture::new();
    let mut lease = f.lease.clone();
    lease["body"]["capabilities"] = json!(["finance", "orders", "quote"]);
    assert!(f.local.prepare(&f.binding, &lease, &f.catalog).is_err());
    let mut catalog = f.catalog.clone();
    catalog["items"][0]["sale"] = json!("99");
    assert!(f.local.prepare(&f.binding, &f.lease, &catalog).is_err());
    let mut binding = f.binding.clone();
    binding.subject = crate::types::new_id().unwrap();
    assert!(f.local.prepare(&binding, &f.lease, &f.catalog).is_err());
    f.local.save("save", &f.body()).unwrap();
}
#[test]
fn clock_rollback_expiry_and_known_revocation_preserve_data_but_stop_new_writes() {
    let f = Fixture::new();
    let receipt = f.local.save("save", &f.body()).unwrap();
    f.local.put("clock", &json!(now() + 3600)).unwrap();
    assert!(f.local.save("save", &f.body()).is_err());
    f.local.put("clock", &json!(now())).unwrap();
    f.local.put("denied", &json!(true)).unwrap();
    assert!(f.local.save("save", &f.body()).is_err());
    assert_eq!(
        f.local
            .c
            .query_row("SELECT count(*) FROM local_orders", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
    f.local.put("denied", &json!(false)).unwrap();
    assert_eq!(
        f.local
            .order(receipt["order_id"].as_str().unwrap())
            .unwrap()["revision"],
        "1"
    );
    let mut context = f.local.meta("context").unwrap().unwrap();
    context["lease"]["body"]["expires_at"] = json!((now() - 1).to_string());
    f.local.put("context", &context).unwrap();
    assert!(f.local.save("save", &f.body()).is_err());
}
