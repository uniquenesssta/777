pub use crate::intake_support::seal;
use crate::intake_support::Test;
use quote_host::{
    files,
    intake::{Intake, FORMAT},
};
use quote_ledger::{integrity, store};
use serde_json::{json, Value};
pub struct App {
    pub t: Test,
}
impl std::ops::Deref for App {
    type Target = Test;
    fn deref(&self) -> &Test {
        &self.t
    }
}
impl App {
    pub fn new(role: &str) -> Self {
        let mut t = Test::role(role);
        let path = t.f.root.join("private/offline-intake.json");
        let mut config = files::read_json(&path).unwrap();
        config["mode"] = json!("apply");
        files::replace_json(&path, &config).unwrap();
        t.intake = Intake::open(&t.f.service).unwrap().unwrap();
        Self { t }
    }
    pub fn op(&self, n: i64) -> Value {
        let mut v = self.t.op(n);
        v["created_at"] = json!(store::now().replace("+00:00", "Z"));
        seal(v)
    }
    pub fn advance(&self) {
        let mut cursor = String::new();
        for _ in 0..20 {
            self.intake.advance(&mut cursor).unwrap();
        }
    }
    pub fn state(&self, v: &Value) -> String {
        self.c()
            .query_row(
                "SELECT state FROM offline_states WHERE operation_id=?",
                [v["operation_id"].as_str()],
                |r| r.get(0),
            )
            .unwrap()
    }
    pub fn inventory(&self) -> Value {
        integrity::inventory(&self.c()).unwrap()
    }
    pub fn order(&self, v: &Value) -> Value {
        let actor = self
            .f
            .service
            .auth
            .authenticate(&self.f.legacy_token)
            .unwrap();
        self.f
            .service
            .order(&actor, v["order_id"].as_str().unwrap())
            .unwrap()
    }
    pub fn grant(&self) {
        let actor = self
            .f
            .service
            .auth
            .authenticate(&self.f.legacy_token)
            .unwrap();
        let cfg = files::read_json(&self.f.root.join("private/offline-intake.json")).unwrap();
        let epoch: i64 = self
            .f
            .c()
            .query_row(
                "SELECT epoch FROM users WHERE id=?",
                [&actor.subject],
                |r| r.get(0),
            )
            .unwrap();
        files::replace_json(&self.f.root.join("private/offline-reviewers.json"),&json!({"format":"777-offline-reviewers-v1","ledger_id":cfg["ledger_id"],"epoch":cfg["epoch"],"reviewers":{actor.subject:epoch}})).unwrap();
    }
    pub fn review(&self, path: &str, data: &Value) -> quote_host::Result<Value> {
        self.as_token(&self.f.legacy_token, path, data)
    }
    pub fn as_token(&self, token: &str, path: &str, data: &Value) -> quote_host::Result<Value> {
        for _ in 0..8 {
            match self.intake.handle("POST", path, token, data) {
                Err(e) if e.status == 429 => {
                    std::thread::sleep(std::time::Duration::from_millis(510))
                }
                r => return r,
            }
        }
        self.intake.handle("POST", path, token, data)
    }
}
pub fn edit(a: &App, first: &Value, n: i64, revision: i64, details: Value, lines: Value) -> Value {
    let mut v = a.op(n);
    v["kind"] = json!("edit");
    v["order_id"] = first["order_id"].clone();
    v["owner_id"] = first["owner_id"].clone();
    v["base"] = json!({"order_revision":revision.to_string(),"previous_operation_id":null});
    v["payload"] = json!({"detail_changes":details,"line_changes":lines,"customer":{}});
    seal(v)
}
pub fn replace(line: &Value, q: &str) -> Value {
    let mut raw = line["raw"].clone();
    raw["q"] = json!(q);
    json!({"op":"replace","line_id":line["line_id"],"raw":raw})
}
pub fn decision(op: &Value, revision: i64, name: &str) -> Value {
    json!({"protocol":FORMAT,"request_id":store::uid().unwrap(),"operation_id":op["operation_id"],"expected_revision":revision.to_string(),"decision":name,"reason":"explicit synthetic reviewer decision"})
}
