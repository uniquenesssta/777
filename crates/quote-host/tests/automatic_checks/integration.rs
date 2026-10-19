use crate::automatic_support::{envelope, Fixture};
use quote_host::{automatic as a, devices::Devices, files, host::Init};
use quote_ledger::store;
use serde_json::json;
#[test]
fn adopted_device_keeps_subject_and_disables_legacy_session_without_disabling_maintenance() {
    let mut f = Fixture::new();
    let legacy = Devices::create(&f.root.join("private/devices.sqlite3")).unwrap();
    let actor = f.service.auth.authenticate(&f.legacy_token).unwrap();
    let grant = legacy
        .issue(
            &f.service.auth,
            &actor,
            &json!({"subject":actor.subject,"delivery":"manager","ttl_seconds":300}),
        )
        .unwrap();
    let device = store::uid().unwrap();
    let secret = a::secret().unwrap();
    let identity = json!({"device_id":device,"device_secret":secret,"delivery":"manager"});
    legacy.enroll(&f.service.auth,&json!({"ticket":grant["ticket"],"device_id":device,"device_secret":secret,"delivery":"manager"})).unwrap();
    let old = legacy.session(&f.service.auth, &identity).unwrap();
    f.service.devices = Some(legacy);
    let (package, key, _) = f.package("manager", &["quote"], 5);
    let profile = a::trust::profile(&f.c()).unwrap();
    let body = envelope(
        a::ENROLLMENT,
        json!({"package_id":package,"site_id":profile["site_id"],"ledger_id":f.ledger,"device_id":device}),
    );
    assert!(
        a::legacy_device::adopt(&f.service, &f.c(), &body, &a::secret().unwrap(), &key).is_err()
    );
    a::legacy_device::adopt(&f.service, &f.c(), &body, &secret, &key).unwrap();
    a::legacy_device::adopt(&f.service, &f.c(), &body, &secret, &key).unwrap();
    let session = a::devices::session(
        &f.c(),
        &envelope(a::SCOPED_AUTH, json!({"device_id":device})),
        &secret,
    )
    .unwrap();
    assert_eq!(session["subject"], actor.subject);
    assert_eq!(session["capabilities"], json!(["quote"]));
    assert!(f
        .service
        .devices
        .as_ref()
        .unwrap()
        .authenticate(&f.service.auth, old["token"].as_str().unwrap())
        .is_err());
    assert!(f
        .service
        .auth
        .login(
            &json!("manager"),
            &json!("fixture-long-password"),
            "post-adoption"
        )
        .is_ok());
}
#[test]
fn issuer_status_contains_public_binding_but_no_keys() {
    let f = Fixture::new();
    let p = f.root.join("issuer.bin");
    a::issuer_state::save(&p,&json!({"format":"777-issuer-pending-v1","binding_complete":true,"profile":a::trust::profile(&f.c()).unwrap(),"issuer_secret":f.issuer_secret,"pair_secret":f.pair_secret}),!cfg!(windows)).unwrap();
    let status = a::issuance::status(&p, !cfg!(windows)).unwrap();
    let raw = status.to_string();
    assert_eq!(status["ready"], true);
    assert!(!raw.contains(&f.issuer_secret));
    assert!(!raw.contains(&f.pair_secret));
}
#[tokio::test]
async fn altered_issuance_candidate_is_rejected_before_any_network_request() {
    let f = Fixture::new();
    let state = f.root.join("issuer.bin");
    let candidate = f.root.join("candidate.bin");
    let input = f.root.join("input.json");
    a::issuer_state::save(&state, &json!({"issuer_id":f.issuer}), !cfg!(windows)).unwrap();
    let body = json!({"package_id":store::uid().unwrap(),"delivery":"sales","permissions":["quote"],"version":"0.1.0","artifact_sha256":"a".repeat(64)});
    files::new_file(&input, &serde_json::to_vec(&body).unwrap()).unwrap();
    a::issuer_state::save(
        &candidate,
        &json!({"issuer_id":f.issuer,"input":{},"secret":"retained"}),
        !cfg!(windows),
    )
    .unwrap();
    let before = std::fs::read(&candidate).unwrap();
    assert_eq!(
        a::issuance::issue(
            &state,
            &input,
            &candidate,
            &f.root.join("out.json"),
            !cfg!(windows)
        )
        .await
        .unwrap_err()
        .code,
        "PACKAGE_ID_CONFLICT"
    );
    assert_eq!(std::fs::read(candidate).unwrap(), before);
    assert!(!f.root.join("out.json").exists());
}
#[tokio::test]
async fn automatic_install_never_replaces_an_existing_unrelated_directory() {
    let f = Fixture::new();
    let (_, key, m) = f.package("manager", &["quote"], 5);
    let path = f.root.join("package.json");
    files::new_file(&path,&serde_json::to_vec(&json!({"format":"777-automatic-package-v1","profile":a::trust::profile(&f.c()).unwrap(),"manifest":m["manifest"],"secret":key})).unwrap()).unwrap();
    let root = f.root.join("unrelated");
    std::fs::create_dir(&root).unwrap();
    std::fs::write(root.join("keep"), b"original").unwrap();
    let init = Init {
        root: root.clone(),
        backups: f.root.join("backup"),
        hosts: vec!["localhost".into()],
        bind: "127.0.0.1".into(),
        port: 8477,
        user: "unused".into(),
        secret: String::new(),
        worker: f.root.join("unused-worker"),
        notices: f.root.join("unused-notices"),
        auxiliary: !cfg!(windows),
    };
    let result = a::installation::join(init, &f.root.join("new-state"), &path)
        .await
        .unwrap_err();
    assert_eq!(result.code, "CLUSTER_JOIN_REQUIRES_NEW_ROOT");
    assert_eq!(std::fs::read(root.join("keep")).unwrap(), b"original");
    assert!(!f.root.join("new-state").exists());
}
#[tokio::test]
async fn closing_a_candidate_for_another_issuer_is_rejected_before_network_and_keeps_journals() {
    let f = Fixture::new();
    let state = f.root.join("close-issuer.bin");
    let candidate = f.root.join("close-candidate.bin");
    a::issuer_state::save(&state,&json!({"issuer_id":f.issuer,"profile":{"site_id":store::uid().unwrap(),"ledger_id":store::uid().unwrap()}}),!cfg!(windows)).unwrap();
    a::issuer_state::save(
        &candidate,
        &json!({"issuer_id":store::uid().unwrap(),"manifest":{"package_id":store::uid().unwrap()}}),
        !cfg!(windows),
    )
    .unwrap();
    let before = std::fs::read(&candidate).unwrap();
    assert_eq!(
        a::issuance::close(&state, &candidate, !cfg!(windows))
            .await
            .unwrap_err()
            .code,
        "PACKAGE_CLOSE_BINDING_CONFLICT"
    );
    assert_eq!(std::fs::read(candidate).unwrap(), before);
}
