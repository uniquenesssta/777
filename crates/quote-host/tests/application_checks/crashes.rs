use super::support::App;
use quote_host::{auth::Auth, intake::Intake, query::Queries, service::Service};
use serde_json::{json, Value};
use std::{path::PathBuf, process::Command};
#[test]
fn resolution_transaction_boundaries() {
    use super::support::{decision, edit, replace};
    if let Some(path) = std::env::var_os("QUOTE777_RESOLUTION_CRASH_INPUT") {
        let data: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        let root = PathBuf::from(data["root"].as_str().unwrap());
        let s = Service {
            root: root.clone(),
            config: data["config"].clone(),
            ledger: root.join("private/ledger.sqlite3"),
            auth: Auth::open(root.join("private/auth.sqlite3")).unwrap(),
            devices: None,
            outputs: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: Some(root.join("private/resolution-fault.txt")),
        };
        let intake = Intake::open(&s).unwrap().unwrap();
        intake
            .handle(
                "POST",
                "/v1/offline/resolve",
                data["token"].as_str().unwrap(),
                &data["request"],
            )
            .unwrap();
        panic!("resolution crash boundary was not reached");
    }
    for (phase, code, income) in [
        ("application_before_commit", 17, "2000"),
        ("application_after_commit", 18, "3000"),
    ] {
        let a = App::new("manager");
        let first = a.op(1);
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
        a.send(vec![one]).unwrap();
        a.advance();
        let two = edit(
            &a,
            &first,
            3,
            1,
            json!({}),
            json!([replace(&first["payload"]["snapshot"]["lines"][0], "3")]),
        );
        a.send(vec![two.clone()]).unwrap();
        a.advance();
        a.grant();
        let request = decision(&two, 2, "apply_candidate");
        let path = a.f.root.join("private/resolution-crash.json");
        std::fs::write(&path,serde_json::to_vec(&json!({"root":a.f.root,"config":a.f.service.config,"token":a.f.legacy_token,"request":request})).unwrap()).unwrap();
        std::fs::write(a.f.root.join("private/resolution-fault.txt"), phase).unwrap();
        let child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "crashes::resolution_transaction_boundaries",
                "--nocapture",
            ])
            .env("QUOTE777_RESOLUTION_CRASH_INPUT", &path)
            .output()
            .unwrap();
        assert_eq!(
            child.status.code(),
            Some(code),
            "{}",
            String::from_utf8_lossy(&child.stderr)
        );
        assert_eq!(a.inventory()["active_income_cents"], income);
        a.review("/v1/offline/resolve", &request).unwrap();
        assert_eq!(a.inventory()["active_income_cents"], "3000");
        let before = a.inventory();
        a.review("/v1/offline/resolve", &request).unwrap();
        assert_eq!(a.inventory(), before);
        assert_eq!(a.state(&two), "conflict");
    }
}
#[test]
fn application_transaction_boundaries() {
    if let Some(path) = std::env::var_os("QUOTE777_APPLICATION_CRASH_INPUT") {
        let data: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        let root = PathBuf::from(data["root"].as_str().unwrap());
        let s = Service {
            root: root.clone(),
            config: data["config"].clone(),
            ledger: root.join("private/ledger.sqlite3"),
            auth: Auth::open(root.join("private/auth.sqlite3")).unwrap(),
            devices: None,
            outputs: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: Some(root.join("private/application-fault.txt")),
        };
        let intake = Intake::open(&s).unwrap().unwrap();
        intake.advance(&mut String::new()).unwrap();
        panic!("application crash boundary was not reached");
    }
    for (phase, code, orders) in [
        ("application_before_commit", 17, 0),
        ("application_after_commit", 18, 1),
    ] {
        let a = App::new("sales");
        let op = a.op(1);
        a.send(vec![op.clone()]).unwrap();
        let path = a.f.root.join("private/application-crash.json");
        std::fs::write(
            &path,
            serde_json::to_vec(&json!({"root":a.f.root,"config":a.f.service.config})).unwrap(),
        )
        .unwrap();
        std::fs::write(a.f.root.join("private/application-fault.txt"), phase).unwrap();
        let result = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "crashes::application_transaction_boundaries",
                "--nocapture",
            ])
            .env("QUOTE777_APPLICATION_CRASH_INPUT", &path)
            .output()
            .unwrap();
        assert_eq!(
            result.status.code(),
            Some(code),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_eq!(a.inventory()["counts"]["orders"], orders);
        assert_eq!(
            a.state(&op),
            if orders == 0 { "received" } else { "applied" }
        );
        a.advance();
        assert_eq!(a.state(&op), "applied");
        let before = a.inventory();
        a.send(vec![op]).unwrap();
        a.advance();
        assert_eq!(a.inventory(), before);
        assert_eq!(before["counts"]["orders"], 1);
    }
}
