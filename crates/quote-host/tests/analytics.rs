use quote_host::query::Queries;
use quote_ledger::store::{self, Actor, Mutation};
use serde_json::json;

#[test]
fn analytics_denies_sales_before_accessing_a_ledger() {
    let mut queries = Queries::new().unwrap();
    let error = queries
        .analytics(
            std::path::Path::new("nonexistent-ledger"),
            &Actor {
                subject: "s".into(),
                role: "sales".into(),
            },
            "period=year&from=2026-01-01&to=2026-12-31",
        )
        .unwrap_err();
    assert_eq!(error.status, 403);
    assert_eq!(queries.full_scans, 0);
}

#[test]
fn full_ledger_aggregate_tracks_void_restore_and_preserves_frozen_prices() {
    let root = std::env::temp_dir().join(format!("777-analytics-{}", store::uid().unwrap()));
    std::fs::create_dir(&root).unwrap();
    let path = root.join("ledger");
    store::create(&path).unwrap();
    let admin = Actor {
        subject: "manager".into(),
        role: "admin".into(),
    };
    let mut c = store::open(&path, true).unwrap();
    let prices = |id: &str, sale: &str| {
        serde_json::from_value(json!({"price_version_id":id,"items":[{"product_id":"P","single":true,"sale":sale,"cost":"4","k":"1"}]})).unwrap()
    };
    store::mutate(
        &mut c,
        Mutation::PublishPrices {
            request_id: store::uid().unwrap(),
            actor: admin.clone(),
            prices: prices("v1", "10"),
            expected_price_version_id: None,
        },
        None,
    )
    .unwrap();
    let mut ids = vec![];
    for i in 0..25 {
        let receipt=store::mutate(&mut c,Mutation::SubmitOrder {request_id:store::uid().unwrap(),actor:Actor {subject:format!("sales{}",i%2),role:"sales".into()},snapshot:serde_json::from_value(json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":"1"}]})).unwrap(),details:json!({"customer":"test","order_ref":i.to_string(),"wechat":""})},None).unwrap();
        ids.push(receipt["order_id"].as_str().unwrap().to_owned());
    }
    let year = time::OffsetDateTime::now_utc().year();
    let q = format!("period=year&from={}-01-01&to={}-12-31", year - 1, year + 1);
    let mut queries = Queries::new().unwrap();
    let v = queries.analytics(&path, &admin, &q).unwrap();
    assert_eq!(v["totals"]["order_count"], 25);
    assert_eq!(v["totals"]["income_cents"], "25000");
    assert_eq!(v["totals"]["profit_cents"], "15000");
    assert_eq!(
        v["buckets"].as_array().unwrap().last().unwrap()["profit_ohlc"]["close_cents"],
        v["totals"]["profit_cents"]
    );
    // A new price must never revalue previously booked orders.
    store::mutate(
        &mut c,
        Mutation::PublishPrices {
            request_id: store::uid().unwrap(),
            actor: admin.clone(),
            prices: prices("v2", "99"),
            expected_price_version_id: Some("v1".into()),
        },
        None,
    )
    .unwrap();
    assert_eq!(
        queries.analytics(&path, &admin, &q).unwrap()["totals"],
        v["totals"]
    );
    for (state, revision, count, income) in [("void", 1, 24, "24000"), ("active", 2, 25, "25000")] {
        store::mutate(
            &mut c,
            Mutation::SetState {
                request_id: store::uid().unwrap(),
                actor: admin.clone(),
                order_id: ids[0].clone(),
                state: state.into(),
                reason: "test".into(),
                expected_revision: revision,
            },
            None,
        )
        .unwrap();
        let next = queries.analytics(&path, &admin, &q).unwrap();
        assert_eq!(next["totals"]["order_count"], count);
        assert_eq!(next["totals"]["income_cents"], income);
        assert_eq!(
            next["buckets"].as_array().unwrap().last().unwrap()["profit_ohlc"]["close_cents"],
            next["totals"]["profit_cents"]
        );
    }
    assert_eq!(queries.full_scans, 1);
    assert_eq!(queries.delta_rows, 2);
    drop(c);
    drop(queries);
    std::fs::remove_dir_all(root).unwrap();
}
