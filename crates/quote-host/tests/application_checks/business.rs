use super::support::*;
use quote_ledger::store;
use serde_json::json;
#[test]
fn create_is_atomic_stable_idempotent_and_does_not_generate_outputs() {
    let a = App::new("sales");
    let op = a.op(1);
    a.send(vec![op.clone()]).unwrap();
    assert_eq!(a.inventory()["counts"]["orders"], 0);
    a.advance();
    assert_eq!(a.state(&op), "applied");
    let view = a.order(&op);
    assert_eq!(view["order_id"], op["order_id"]);
    assert_eq!(
        view["lines"][0]["line_id"],
        op["payload"]["snapshot"]["lines"][0]["line_id"]
    );
    assert_eq!(view["income_cents"], "1000");
    assert_eq!(view["created_at"], op["created_at"]);
    let before = a.inventory();
    let receipt = a.receipts(vec![op["operation_id"].clone()]);
    assert_eq!(receipt["receipts"][0]["result"]["revision"], "1");
    assert!(receipt["receipts"][0]["result"].get("cost_cents").is_none());
    a.send(vec![op.clone()]).unwrap();
    a.advance();
    assert_eq!(a.inventory(), before);
    assert_eq!(
        a.f.service
            .outputs
            .as_ref()
            .unwrap()
            .connection()
            .unwrap()
            .query_row("SELECT count(*) FROM jobs", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn out_of_order_dependency_restarts_and_unrelated_orders_continue() {
    let a = App::new("sales");
    let first = a.op(1);
    let mut note = a.op(2);
    note["kind"] = json!("append_note");
    note["order_id"] = first["order_id"].clone();
    note["base"] = json!({"order_revision":null,"previous_operation_id":first["operation_id"]});
    note["payload"] = json!({"note_id":store::uid().unwrap(),"body":"durable note"});
    let note = seal(note);
    let other = a.op(3);
    a.send(vec![note.clone(), other.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&note), "waiting_dependency");
    assert_eq!(a.state(&other), "applied");
    a.send(vec![first.clone()]).unwrap();
    let reopened = quote_host::intake::Intake::open(&a.f.service)
        .unwrap()
        .unwrap();
    let mut cursor = String::new();
    for _ in 0..12 {
        reopened.advance(&mut cursor).unwrap();
    }
    assert_eq!(a.state(&note), "applied");
    assert_eq!(
        a.order(&first)["notes"][0]["note_id"],
        note["payload"]["note_id"]
    );
    assert_eq!(a.inventory()["counts"]["orders"], 2);
}
#[test]
fn a_new_parent_bypasses_the_waiting_cursor_and_wakes_its_child() {
    let a = App::new("sales");
    let mut first = a.op(1);
    first["operation_id"] = json!("00000000-0000-4000-8000-000000000001");
    let first = seal(first);
    let mut note = a.op(2);
    note["kind"] = json!("append_note");
    note["order_id"] = first["order_id"].clone();
    note["base"] = json!({"order_revision":null,"previous_operation_id":first["operation_id"]});
    note["payload"] = json!({"note_id":store::uid().unwrap(),"body":"wake this dependency"});
    let note = seal(note);
    a.send(vec![note.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&note), "waiting_dependency");
    let mut cursor = "ffffffff-ffff-ffff-ffff-ffffffffffff".into();
    a.send(vec![first.clone()]).unwrap();
    a.intake.advance(&mut cursor).unwrap();
    assert_eq!(a.state(&first), "applied");
    assert_eq!(a.state(&note), "received");
    a.intake.advance(&mut cursor).unwrap();
    assert_eq!(a.state(&note), "applied");
    assert_eq!(a.order(&first)["notes"].as_array().unwrap().len(), 1);
    a.inventory();
}
#[test]
fn unrelated_line_and_detail_changes_three_way_merge_with_full_history() {
    let a = App::new("manager");
    let mut first = a.op(1);
    let mut line = first["payload"]["snapshot"]["lines"][0].clone();
    line["line_id"] = json!(store::uid().unwrap());
    first["payload"]["snapshot"]["lines"]
        .as_array_mut()
        .unwrap()
        .push(line.clone());
    let first = seal(first);
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
    a.send(vec![one.clone()]).unwrap();
    a.advance();
    let two = edit(
        &a,
        &first,
        3,
        1,
        json!({"order_ref":"merged-ref"}),
        json!([replace(&line, "3")]),
    );
    a.send(vec![two.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&two), "applied");
    let view = a.order(&first);
    assert_eq!(view["income_cents"], "5000");
    assert_eq!(view["history"].as_array().unwrap().len(), 2);
    assert_eq!(view["details"]["order_ref"], "merged-ref");
    assert_eq!(view["lines"][1]["line_id"], line["line_id"]);
    assert_eq!(a.inventory()["active_income_cents"], "5000");
}
#[test]
fn independent_additions_merge_but_same_line_and_discount_group_do_not() {
    let a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let mut extra = first["payload"]["snapshot"]["lines"][0].clone();
    extra["line_id"] = json!(store::uid().unwrap());
    let add = edit(
        &a,
        &first,
        2,
        1,
        json!({}),
        json!([{"op":"add","line_id":extra["line_id"],"raw":extra["raw"]}]),
    );
    a.send(vec![add]).unwrap();
    a.advance();
    let change = edit(
        &a,
        &first,
        3,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "2")]),
    );
    a.send(vec![change.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&change), "applied");
    let conflict = edit(
        &a,
        &first,
        4,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "3")]),
    );
    a.send(vec![conflict.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&conflict), "conflict");
    assert_eq!(a.order(&first)["income_cents"], "3000");
    let discount = edit(
        &a,
        &first,
        5,
        1,
        json!({}),
        json!([{"op":"add","line_id":store::uid().unwrap(),"raw":{"line_kind":"discount","percent":"90","name":""}}]),
    );
    a.send(vec![discount.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&discount), "conflict");
}
#[test]
fn same_customer_distinct_order_numbers_group_without_combining_orders() {
    let a = App::new("sales");
    let mut first = a.op(1);
    first["payload"]["customer"] = json!({});
    let first = seal(first);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let mut second = a.op(2);
    second["payload"]["customer"] = json!({});
    let second = seal(second);
    a.send(vec![second.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&second), "applied");
    assert_eq!(
        a.order(&first)["customer_id"],
        a.order(&second)["customer_id"]
    );
    assert_eq!(a.inventory()["counts"]["orders"], 2);
    let mut duplicate = a.op(3);
    duplicate["payload"]["details"]["order_ref"] = first["payload"]["details"]["order_ref"].clone();
    let duplicate = seal(duplicate);
    a.send(vec![duplicate.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&duplicate), "conflict");
    assert_eq!(a.inventory()["active_income_cents"], "2000");
}
#[test]
fn historical_lease_prices_are_not_silently_replaced_by_new_catalog() {
    let mut a = App::new("sales");
    let first = a.op(1);
    a.t.f.service.handle("POST","/v1/prices",&a.t.f.legacy_token,&json!({"request_id":store::uid().unwrap(),"expected_price_version_id":"offline-fixture","prices":{"price_version_id":"newer","items":[{"product_id":"item","sale":"99","cost":"50","k":"1","single":true}]}}),"","test").unwrap();
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&first), "applied");
    assert_eq!(a.order(&first)["income_cents"], "1000");
}
#[test]
fn state_changes_are_authorized_and_cannot_overwrite_concurrent_edit() {
    let a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let change = edit(&a, &first, 2, 1, json!({"order_ref":"changed"}), json!([]));
    a.send(vec![change]).unwrap();
    a.advance();
    let mut state = a.op(3);
    state["kind"] = json!("set_state");
    state["order_id"] = first["order_id"].clone();
    state["base"] = json!({"order_revision":"1","previous_operation_id":null});
    state["payload"] = json!({"state":"void","reason":"explicit"});
    let state = seal(state);
    a.send(vec![state.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&state), "conflict");
    let mut valid = state.clone();
    valid["operation_id"] = json!(store::uid().unwrap());
    valid["device_sequence"] = json!("4");
    valid["base"]["order_revision"] = json!("2");
    let valid = seal(valid);
    a.send(vec![valid.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&valid), "applied");
    assert_eq!(a.inventory()["active_income_cents"], "0");
}

#[test]
fn independent_authenticated_manager_devices_merge_without_changing_owner() {
    let a = App::new("manager");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    let one = edit(
        &a,
        &first,
        2,
        1,
        json!({"order_ref":"peer-edit"}),
        json!([]),
    );
    a.send(vec![one]).unwrap();
    a.advance();
    let (package, key, _) =
        a.f.package("manager", &["edit_orders", "orders", "quote"], 8);
    let (body, secret) = a.f.candidate(&package);
    let session = a.f.activate(&body, &key, &secret);
    let token = session["token"].as_str().unwrap();
    let lease = a
        .as_token(
            token,
            "/v1/offline/lease",
            &json!({"protocol":quote_host::intake::FORMAT,"request_id":store::uid().unwrap()}),
        )
        .unwrap();
    let mut two = edit(
        &a,
        &first,
        1,
        1,
        json!({}),
        json!([replace(&first["payload"]["snapshot"]["lines"][0], "3")]),
    );
    for key in ["device_id", "stream_id", "lease_id"] {
        two[key] = lease["body"][key].clone();
    }
    let two = seal(two);
    a.as_token(token,"/v1/offline/operations",&json!({"protocol":quote_host::intake::FORMAT,"batch_id":store::uid().unwrap(),"operations":[two.clone()]})).unwrap();
    a.advance();
    assert_eq!(a.state(&two), "applied");
    let view = a.order(&first);
    assert_eq!(view["owner_id"], first["owner_id"]);
    assert_eq!(view["details"]["order_ref"], "peer-edit");
    assert_eq!(view["income_cents"], "3000");
}

#[test]
fn independent_notes_commute_but_sales_cannot_void_an_order() {
    let a = App::new("sales");
    let first = a.op(1);
    a.send(vec![first.clone()]).unwrap();
    a.advance();
    for n in [2, 3] {
        let mut note = a.op(n);
        note["kind"] = json!("append_note");
        note["order_id"] = first["order_id"].clone();
        note["base"] = json!({"order_revision":"1","previous_operation_id":null});
        note["payload"] = json!({"note_id":store::uid().unwrap(),"body":format!("note {n}")});
        let note = seal(note);
        a.send(vec![note.clone()]).unwrap();
        a.advance();
        assert_eq!(a.state(&note), "applied");
    }
    let mut state = a.op(4);
    state["kind"] = json!("set_state");
    state["order_id"] = first["order_id"].clone();
    state["base"] = json!({"order_revision":"3","previous_operation_id":null});
    state["payload"] = json!({"state":"void","reason":"cannot authorize itself"});
    let state = seal(state);
    a.send(vec![state.clone()]).unwrap();
    a.advance();
    assert_eq!(a.state(&state), "rejected");
    assert_eq!(a.order(&first)["notes"].as_array().unwrap().len(), 2);
    assert_eq!(a.inventory()["active_income_cents"], "1000");
}
