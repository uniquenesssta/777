use crate::automatic_support::{envelope, Fixture};
use quote_host::{auth, automatic as a, protocol};
use quote_ledger::store;
use serde_json::{json, Value};
#[test]
fn multi_install_identity_retry_capacity_and_secret_storage() {
    let f = Fixture::new();
    let (package, secret, _) = f.package("sales", &["quote", "orders"], 2);
    let (d1, s1) = f.candidate(&package);
    let (d2, s2) = f.candidate(&package);
    let first = f.activate(&d1, &secret, &s1);
    let second = f.activate(&d2, &secret, &s2);
    assert_ne!(first["subject"], second["subject"]);
    assert_eq!(
        a::devices::enroll(&f.c(), &d1, &secret).unwrap()["subject"],
        first["subject"]
    );
    assert_eq!(
        f.c()
            .query_row(
                "SELECT devices FROM package_grants WHERE id=?",
                [&package],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        2
    );
    assert!(a::devices::enroll(&f.c(), &f.candidate(&package).0, &secret).is_err());
    let mut changed = d1.clone();
    changed["device_secret_hash"] = json!(store::hash("other"));
    assert!(a::devices::enroll(&f.c(), &changed, &secret).is_err());
    let raw = std::fs::read(&f.service.auth.path).unwrap();
    for secret in [
        &secret,
        &s1,
        &s2,
        &f.issuer_secret,
        &f.pair_secret,
        first["token"].as_str().unwrap(),
    ] {
        assert!(!raw.windows(secret.len()).any(|w| w == secret.as_bytes()));
    }
}
#[test]
fn expiry_close_and_revocation_are_distinct_and_live_sessions_are_checked() {
    let f = Fixture::new();
    let (package, secret, _) = f.package("manager", &["quote"], 3);
    let (d, s) = f.candidate(&package);
    let session = f.activate(&d, &secret, &s);
    let token = session["token"].as_str().unwrap();
    a::packages::close(
        &f.c(),
        &f.issuer,
        &package,
        &envelope(a::ISSUANCE, json!({})),
        false,
    )
    .unwrap();
    assert!(a::sessions::lookup(&f.c(), token).is_ok());
    assert!(a::devices::enroll(&f.c(), &d, &secret).is_ok());
    assert!(a::devices::enroll(&f.c(), &f.candidate(&package).0, &secret).is_err());
    a::packages::close(
        &f.c(),
        &f.issuer,
        &package,
        &envelope(a::ISSUANCE, json!({})),
        true,
    )
    .unwrap();
    assert!(a::sessions::lookup(&f.c(), token).is_err());
    assert!(a::devices::enroll(&f.c(), &d, &secret).is_err());
}
#[test]
fn forged_manifest_cross_site_and_password_login_do_not_elevate() {
    let mut f = Fixture::new();
    let (package, secret, mut data) = f.package("sales", &["quote"], 2);
    data["manifest"]["package_id"] = json!(store::uid().unwrap());
    data["manifest"]["capabilities"] = json!(["finance", "quote"]);
    assert!(a::packages::create(&f.c(), &f.issuer, &data).is_err());
    let (d, s) = f.candidate(&package);
    let mut wrong = d.clone();
    wrong["site_id"] = json!(store::uid().unwrap());
    assert!(a::devices::enroll(&f.c(), &wrong, &secret).is_err());
    let session = f.activate(&d, &secret, &s);
    let subject = session["subject"].as_str().unwrap();
    let user: String = f
        .c()
        .query_row("SELECT username FROM users WHERE id=?", [subject], |r| {
            r.get(0)
        })
        .unwrap();
    let salt = auth::random::<16>().unwrap();
    f.c()
        .execute(
            "UPDATE users SET salt=?,verifier=? WHERE id=?",
            rusqlite::params![
                salt.as_slice(),
                auth::verifier("known-test-password", &salt).unwrap(),
                subject
            ],
        )
        .unwrap();
    assert!(f
        .service
        .auth
        .login(&json!(user), &json!("known-test-password"), "fixture")
        .is_err());
    let token = session["token"].as_str().unwrap();
    for path in [
        "/v1/accounts",
        "/v1/device-grants",
        "/v1/cluster/invite",
        "/v1/analytics",
        "/v1/orders",
    ] {
        assert!(f
            .service
            .handle("POST", path, token, &json!({}), "", "fixture")
            .is_err());
    }
    assert!(f
        .service
        .handle(
            "GET",
            "/v1/me",
            &f.issuer_token,
            &Value::Null,
            "",
            "fixture"
        )
        .is_err());
}
#[test]
fn same_role_upgrade_changes_scope_without_changing_subject_and_revoked_device_stays_revoked() {
    let f = Fixture::new();
    let (p1, s1, _) = f.package("manager", &["quote", "orders", "finance"], 3);
    let (p2, s2, _) = f.package("manager", &["quote"], 3);
    let (d, secret) = f.candidate(&p1);
    let session = f.activate(&d, &s1, &secret);
    let old = session["token"].as_str().unwrap();
    a::devices::upgrade(
        &f.c(),
        &envelope(a::ENROLLMENT, json!({"package_id":p2})),
        old,
        &s2,
    )
    .unwrap();
    assert!(a::sessions::lookup(&f.c(), old).is_err());
    let next = a::devices::session(
        &f.c(),
        &envelope(a::SCOPED_AUTH, json!({"device_id":d["device_id"]})),
        &secret,
    )
    .unwrap();
    assert_eq!(next["subject"], session["subject"]);
    assert_eq!(next["capabilities"], json!(["quote"]));
    a::devices::revoke(&f.c(), d["device_id"].as_str().unwrap()).unwrap();
    assert!(a::devices::session(
        &f.c(),
        &envelope(a::SCOPED_AUTH, json!({"device_id":d["device_id"]})),
        &secret
    )
    .is_err());
}
#[test]
fn first_pairing_rejects_wrong_secret_and_challenge_and_confirmation_closes_it() {
    let f = Fixture::new();
    let body = envelope(
        a::ISSUANCE,
        json!({"upgrade_id":f.kit.upgrade_id,"challenge":store::hash("fixture challenge")}),
    );
    assert!(a::trust::pair(&f.c(), &body, &a::secret().unwrap()).is_err());
    let result = a::trust::pair(&f.c(), &body, &f.pair_secret).unwrap();
    assert_eq!(result["profile"]["ledger_id"], f.ledger);
    let mut other = body.clone();
    other["challenge"] = json!(store::hash("other"));
    assert!(a::trust::pair(&f.c(), &other, &f.pair_secret).is_err());
    assert!(a::trust::confirm(&f.c(), &other, &f.issuer_token).is_err());
    a::trust::confirm(&f.c(), &body, &f.issuer_token).unwrap();
    a::trust::confirm(&f.c(), &body, &f.issuer_token).unwrap();
    assert!(a::trust::pair(&f.c(), &body, &f.pair_secret).is_err());
    assert!(protocol::decode(br#"{"protocol":"x","protocol":"y"}"#, 65536).is_err());
}
#[test]
fn expired_package_stops_new_identity_but_keeps_registered_identity() {
    let f = Fixture::new();
    let (package, secret, _) = f.package("sales", &["quote"], 3);
    let (d, s) = f.candidate(&package);
    let session = f.activate(&d, &secret, &s);
    let (mut manifest, _) = a::packages::get(&f.c(), &package).unwrap();
    manifest.enroll_before = 0;
    f.c()
        .execute(
            "UPDATE package_grants SET manifest_json=? WHERE id=?",
            rusqlite::params![serde_json::to_string(&manifest).unwrap(), package],
        )
        .unwrap();
    assert!(a::sessions::lookup(&f.c(), session["token"].as_str().unwrap()).is_ok());
    assert!(a::devices::enroll(&f.c(), &d, &secret).is_ok());
    assert!(a::devices::enroll(&f.c(), &f.candidate(&package).0, &secret).is_err());
}
