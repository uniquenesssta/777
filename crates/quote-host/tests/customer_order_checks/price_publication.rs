use super::*;

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
