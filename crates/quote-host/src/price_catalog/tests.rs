use super::*;

#[test]
fn daily_sequence_uses_beijing_day_and_committed_revision_even_with_identical_timestamps() {
    // Isolated timestamp boundary fixture; real publication is covered separately.
    let c = Connection::open_in_memory().unwrap();
    c.execute_batch(
        "CREATE TABLE price_versions(price_id TEXT,created_at TEXT);
        CREATE TABLE requests(operation TEXT,result_json TEXT,ledger_revision INTEGER);",
    )
    .unwrap();
    let versions = [
        ("before", "2026-10-19T15:59:59+00:00", 1),
        ("z-first", "2026-10-19T16:00:00+00:00", 4),
        ("a-second", "2026-10-19T16:00:00+00:00", 9),
        ("next-day", "2026-10-20T16:00:00+00:00", 12),
    ];
    for (id, stamp, revision) in versions {
        c.execute("INSERT INTO price_versions VALUES(?,?)", [id, stamp])
            .unwrap();
        c.execute(
            "INSERT INTO requests VALUES('publish_prices',?,?)",
            rusqlite::params![
                serde_json::json!({"price_version_id":id}).to_string(),
                revision
            ],
        )
        .unwrap();
    }
    for ((id, stamp, _), expected) in versions.into_iter().zip([1, 1, 2, 1]) {
        assert_eq!(publication_sequence(&c, stamp, id).unwrap(), expected);
    }
}
