use crate::automatic_support::Fixture;
use quote_host::intake::{self, Intake};
use quote_ledger::store;
use serde_json::{json, Value};
pub struct Test {
    pub f: Fixture,
    pub intake: Intake,
    pub token: String,
    pub lease: Value,
    pub body: Value,
}
impl Test {
    pub fn new() -> Self {
        Self::role("sales")
    }
    pub fn role(role: &str) -> Self {
        let mut f = Fixture::new();
        f.service.handle("POST","/v1/prices",&f.legacy_token,&json!({"request_id":store::uid().unwrap(),"expected_price_version_id":null,"prices":{"price_version_id":"offline-fixture","items":[{"product_id":"item","sale":"10","cost":"4","k":"1","single":true}]}}),"","test").unwrap();
        let (package, key, _) = f.package(role, &["quote", "orders", "edit_orders"], 8);
        let (body, secret) = f.candidate(&package);
        let session = f.activate(&body, &key, &secret);
        let token = session["token"].as_str().unwrap().to_owned();
        intake::setup::provision(&f.service).unwrap();
        let intake = Intake::open(&f.service).unwrap().unwrap();
        let lease = intake
            .handle(
                "POST",
                "/v1/offline/lease",
                &token,
                &json!({"protocol":intake::FORMAT,"request_id":store::uid().unwrap()}),
            )
            .unwrap();
        Self {
            f,
            intake,
            token,
            lease,
            body,
        }
    }
    pub fn op(&self, n: i64) -> Value {
        let b = &self.lease["body"];
        seal(
            json!({"protocol":intake::FORMAT,"site_id":b["site_id"],"ledger_id":b["ledger_id"],"device_id":b["device_id"],"stream_id":b["stream_id"],"owner_id":b["subject"],"lease_id":b["lease_id"],"operation_id":store::uid().unwrap(),"device_sequence":n.to_string(),"order_id":store::uid().unwrap(),"kind":"create","base":{"order_revision":null,"previous_operation_id":null},"created_at":"2026-10-19T10:00:00.000000Z","rule_version":"business-v1","numeric_profile":"numeric-v1","payload":{"snapshot":{"price_version_id":"offline-fixture","lines":[{"line_id":store::uid().unwrap(),"raw":{"line_kind":"normal","product_id":"item","q":"1","h":"","w":"","name":""}}]},"details":{"customer":"synthetic","order_ref":format!("offline-{n}"),"wechat":""},"customer":{"new_customer":true}}}),
        )
    }
    pub fn call(&self, path: &str, v: &Value) -> quote_host::Result<Value> {
        for _ in 0..4 {
            match self.intake.handle("POST", path, &self.token, v) {
                Err(e) if e.status == 429 && e.code == "OFFLINE_INTAKE_CAPACITY" => {
                    std::thread::sleep(std::time::Duration::from_millis(510))
                }
                result => return result,
            }
        }
        self.intake.handle("POST", path, &self.token, v)
    }
    pub fn send(&self, ops: Vec<Value>) -> quote_host::Result<Value> {
        self.call(
            "/v1/offline/operations",
            &json!({"protocol":intake::FORMAT,"batch_id":store::uid().unwrap(),"operations":ops}),
        )
    }
    pub fn receipts(&self, ids: Vec<Value>) -> Value {
        self.call(
            "/v1/offline/receipts",
            &json!({"protocol":intake::FORMAT,"operation_ids":ids}),
        )
        .unwrap()
    }
    pub fn c(&self) -> rusqlite::Connection {
        store::open(&self.f.service.ledger, true).unwrap()
    }
}
pub fn seal(mut v: Value) -> Value {
    v["content_sha256"] = json!(intake::envelope::digest(&v).unwrap());
    v
}
pub fn edit(t: &Test, first: &Value, n: i64) -> Value {
    let mut v = t.op(n);
    v["kind"] = json!("append_note");
    v["order_id"] = first["order_id"].clone();
    v["base"] = json!({"order_revision":null,"previous_operation_id":first["operation_id"]});
    v["payload"] = json!({"note_id":store::uid().unwrap(),"body":"next saved change"});
    seal(v)
}
