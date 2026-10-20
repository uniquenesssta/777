use super::*;
#[test]
fn failed_output_deletion_is_persistent_idempotent_and_does_not_touch_orders() {
    let mut f = Fixture::new();
    f.post("/v1/settings", json!({"revision":1,"export_dir":f.root.to_string_lossy(),"image_dir":f.root.to_string_lossy()}));
    f.prices("v1", Value::Null, "10");
    let saved = f.post("/v1/order-save", draft("v1", "cleanup"));
    let order_id = saved["order_id"].as_str().unwrap().to_string();
    let before = f.get(&format!("/v1/orders/{order_id}"));
    // Fixture has no CJK image font: run the real worker to produce an actual failed export.
    let job = f.output(json!({"request_id":store::uid().unwrap(),"order_id":order_id,"expected_revision":1,"kind":"quote_png"}));
    let job_id = job["job_id"].as_str().unwrap().to_string();
    assert_eq!(f.get(&format!("/v1/outputs/{job_id}"))["state"], "failed");
    let path = format!("/v1/outputs/{job_id}/delete");
    let request = json!({"request_id":store::uid().unwrap()});
    let deleted = f.post(&path, request.clone());
    assert_eq!(deleted["deleted"], true);
    assert_eq!(f.post(&path, request), deleted);
    assert_eq!(f.get("/v1/outputs")["total"], 0);
    assert_eq!(f.get(&format!("/v1/orders/{order_id}")), before);
    assert!(f
        .s
        .handle(
            "POST",
            &format!("/v1/outputs/{job_id}/retry"),
            &f.token,
            &json!({"request_id":store::uid().unwrap()}),
            "",
            "test"
        )
        .is_err());
    let outputs = f.s.outputs.as_ref().unwrap();
    let connection = outputs.connection().unwrap();
    assert_eq!(
        connection
            .query_row(
                "SELECT count(*) FROM events WHERE operation='delete'",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
    let reopened = Outputs::open(
        outputs.path.clone(),
        store::verify(&store::open(&f.s.ledger, false).unwrap()).unwrap()["ledger_id"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let actor = store::Actor {
        subject: "manager".into(),
        role: "admin".into(),
    };
    assert_eq!(reopened.listing(&actor).unwrap()["total"], 0);
    let other = store::Actor {
        subject: "another-sales".into(),
        role: "sales".into(),
    };
    assert!(outputs
        .delete_failed(&other, &job_id, &store::uid().unwrap())
        .is_err());
    let done=f.output(json!({"request_id":store::uid().unwrap(),"order_id":order_id,"expected_revision":1,"kind":"excel_quote"}));
    let done_id = done["job_id"].as_str().unwrap();
    assert_eq!(f.get(&format!("/v1/outputs/{done_id}"))["state"], "done");
    assert_eq!(
        f.s.outputs
            .as_ref()
            .unwrap()
            .delete_failed(&actor, done_id, &store::uid().unwrap())
            .unwrap_err()
            .code,
        "OUTPUT_DELETE_FAILED_ONLY"
    );
}
