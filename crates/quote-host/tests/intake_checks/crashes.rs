use super::support::Test;
use quote_host::{
    auth::Auth,
    intake::{self, Intake},
    query::Queries,
    service::Service,
};
use quote_ledger::store;
use serde_json::{json, Value};
use std::{path::PathBuf, process::Command};
#[test]
fn transaction_boundaries() {
    if let Some(input) = std::env::var_os("QUOTE777_INTAKE_CRASH_INPUT") {
        let input: Value = serde_json::from_slice(&std::fs::read(input).unwrap()).unwrap();
        let root = PathBuf::from(input["root"].as_str().unwrap());
        let service = Service {
            root: root.clone(),
            config: input["config"].clone(),
            ledger: root.join("private/ledger.sqlite3"),
            auth: Auth::open(root.join("private/auth.sqlite3")).unwrap(),
            devices: None,
            outputs: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: Some(root.join("private/intake-fault.txt")),
        };
        let i = Intake::open(&service).unwrap().unwrap();
        i.handle(
            "POST",
            "/v1/offline/operations",
            input["token"].as_str().unwrap(),
            &input["request"],
        )
        .unwrap();
        panic!("owned child did not reach the requested crash boundary");
    }
    for (phase, code, expected) in [
        ("intake_before_commit", 17, "not_found"),
        ("intake_after_commit", 18, "received"),
    ] {
        let t = Test::new();
        let op = t.op(1);
        let path = t.f.root.join("private/crash-input.json");
        let request =
            json!({"protocol":intake::FORMAT,"batch_id":store::uid().unwrap(),"operations":[op]});
        std::fs::write(&path,serde_json::to_vec(&json!({"root":t.f.root,"config":t.f.service.config,"token":t.token,"request":request})).unwrap()).unwrap();
        std::fs::write(t.f.root.join("private/intake-fault.txt"), phase).unwrap();
        let result = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "crashes::transaction_boundaries", "--nocapture"])
            .env("QUOTE777_INTAKE_CRASH_INPUT", &path)
            .output()
            .unwrap();
        assert_eq!(
            result.status.code(),
            Some(code),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        let id = request["operations"][0]["operation_id"].clone();
        assert_eq!(t.receipts(vec![id])["receipts"][0]["state"], expected);
        t.send(vec![request["operations"][0].clone()]).unwrap();
        assert_eq!(
            t.c()
                .query_row("SELECT count(*) FROM offline_operations", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            1
        );
    }
}
