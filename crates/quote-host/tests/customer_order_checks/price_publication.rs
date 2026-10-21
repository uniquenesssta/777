use super::*;

#[test]
fn empty_versions_publish_persist_and_restore_without_erasing_orders_or_prices() {
    let mut f = Fixture::new();
    let publish = |version: &str, previous: Value| json!({"request_id":store::uid().unwrap(),"expected_price_version_id":previous,"prices":{"price_version_id":version,"items":[]}});
    f.post("/v1/prices", publish("empty-first", Value::Null));
    let first = f.get("/v1/prices");
    assert_eq!(first["items"], json!([]));
    assert_eq!(first["publication_sequence"], "1");
    f.prices("populated", json!("empty-first"), "10");
    let order = f.post("/v1/order-save", draft("populated", "00001"));
    let path = format!("/v1/orders/{}", order["order_id"].as_str().unwrap());
    let original = f.get(&path);
    let clear = publish("cleared", json!("populated"));
    let saved = f.post("/v1/prices", clear.clone());
    assert_eq!(f.post("/v1/prices", clear), saved);
    let empty = f.get("/v1/prices");
    assert_eq!(empty["items"], json!([]));
    assert_eq!(empty["price_version_id"], "cleared");
    assert_eq!(empty["publication_sequence"], "3");
    assert_eq!(f.get(&path), original);
    let stale = publish("stale", json!("populated"));
    assert!(f
        .s
        .handle("POST", "/v1/prices", &f.token, &stale, "", "test")
        .is_err());
    let calculation = f.post(
        "/v1/calculate",
        json!({"snapshot":draft("cleared", "") ["snapshot"]}),
    );
    assert_eq!(calculation["status"], "VALIDATION");
    assert_eq!(calculation["issues"][0]["reason"], "PRODUCT_NOT_FOUND");
    let old =
        f.s.handle(
            "POST",
            "/v1/calculate",
            &f.token,
            &json!({"snapshot":draft("populated", "")["snapshot"]}),
            "",
            "test",
        )
        .unwrap_err();
    assert_eq!(old.code, "PRICE_VERSION_CHANGED");
    let captured = recovery::capture(&f.s, "2026-10-21").unwrap();
    let restored = f.root.join("restored-empty.sqlite3");
    recovery::restore_ledger(
        &recovery::decode(&recovery::encode(&captured).unwrap()).unwrap(),
        &restored,
    )
    .unwrap();
    let c = store::open(&restored, false).unwrap();
    assert_eq!(
        store::active_prices(&c).unwrap().price_version_id,
        "cleared"
    );
    assert!(store::active_prices(&c).unwrap().items.is_empty());
    assert_eq!(store::load_prices(&c, "populated").unwrap().items.len(), 1);
    assert_eq!(integrity::inventory(&c).unwrap()["counts"]["orders"], 1);
    f.prices("refilled", json!("cleared"), "20");
    assert_eq!(f.get("/v1/prices")["publication_sequence"], "4");
    assert_eq!(f.get(&path), original);
}

#[test]
fn published_catalog_date_and_sequence_survive_refresh_and_database_reopen() {
    let mut f = Fixture::new();
    f.prices("z-first", Value::Null, "10");
    let first = f.get("/v1/prices");
    assert_eq!(first["publication_sequence"], "1");
    assert!(first["published_at"].as_str().unwrap().contains('T'));
    assert_eq!(first, f.get("/v1/prices"));
    f.prices("a-second", json!("z-first"), "11");
    let second = f.get("/v1/prices");
    assert_eq!(second["publication_sequence"], "2");
    assert_ne!(first["price_version_id"], second["price_version_id"]);
    let c = store::open(&f.s.ledger, false).unwrap();
    let stamp: String = c
        .query_row(
            "SELECT created_at FROM price_versions WHERE price_id='a-second'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(second["published_at"], stamp);
    drop(c);
    assert_eq!(second, f.get("/v1/prices"));
}
