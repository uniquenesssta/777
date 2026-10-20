use crate::automatic_support::Fixture;
use quote_host::{auth::Auth, automatic as a};
#[cfg(not(windows))]
use serde_json::json;
#[test]
fn schema_upgrade_is_idempotent_and_rejects_unknown_schema() {
    let f = Fixture::new();
    let old = f.root.join("legacy.sqlite3");
    let auth = Auth::create(&old, "admin", "fixture-long-password").unwrap();
    let id: String = auth
        .connection()
        .unwrap()
        .query_row("SELECT id FROM users", [], |r| r.get(0))
        .unwrap();
    a::schema::upgrade(&old).unwrap();
    a::schema::upgrade(&old).unwrap();
    assert_eq!(a::schema::version(&old).unwrap(), 2);
    let auth = Auth::open(old.clone()).unwrap();
    assert_eq!(
        auth.connection()
            .unwrap()
            .query_row("SELECT id FROM users", [], |r| r.get::<_, String>(0))
            .unwrap(),
        id
    );
    auth.connection()
        .unwrap()
        .execute_batch("CREATE TABLE unexpected(x TEXT);")
        .unwrap();
    assert!(a::schema::upgrade(&old).is_err());
}
#[test]
#[cfg(not(windows))]
fn upgrade_and_interrupted_publication_preserve_ledger_tls_backups_and_task_identity() {
    use quote_host::files;
    use quote_ledger::{integrity, store};
    let f = Fixture::new();
    let private = f.root.join("private");
    let old = files::sha(&private.join("rust-service-host.exe")).unwrap();
    let config = json!({"schema":"777-host-v1","ledger_id":f.ledger,"backup_store_id":store::uid().unwrap(),"backup_dir":f.root.join("backup"),"bind":"192.168.4.23","port":8477,"certificate_sha256":quote_host::host::certificate_sha(&private.join("tls-cert.pem")).unwrap(),"private_security":{},"maintenance":false,"rust_host_sha256":old});
    files::replace_json(&private.join("service.json"), &config).unwrap();
    let deployment = json!({"schema":"777-site-deployment-v1","root":f.root,"owner_sid":"fixture-owner","machine":"fixture-machine","owner_account":"fixture-account","active_address":"192.168.4.23","port":8477,"ledger_id":f.ledger,"host_sha256":old,"runner_sha256":files::sha(&private.join("host-run.ps1")).unwrap(),"identity_sha256":files::sha(&private.join("host-identity.ps1")).unwrap(),"autostart":"fixture-existing-task"});
    files::replace_json(&private.join("deployment.json"), &deployment).unwrap();
    let kit = f.root.join("kit.json");
    files::new_file(&kit, &serde_json::to_vec(&f.kit).unwrap()).unwrap();
    let notices = private.join("rust-host-notices.txt");
    let inv = integrity::inventory(&store::open(&f.service.ledger, false).unwrap()).unwrap();
    let tls = files::sha(&private.join("tls-key.pem")).unwrap();
    a::upgrade::apply(&f.root, &kit, &notices, true).unwrap();
    // Simulate a crash between exe replacement and service/deployment JSON publication.
    files::replace_json(&private.join("service.json"), &config).unwrap();
    files::replace_json(&private.join("deployment.json"), &deployment).unwrap();
    a::upgrade::apply(&f.root, &kit, &notices, true).unwrap();
    a::upgrade::apply(&f.root, &kit, &notices, true).unwrap();
    assert_eq!(
        inv,
        integrity::inventory(&store::open(&f.service.ledger, false).unwrap()).unwrap()
    );
    assert_eq!(tls, files::sha(&private.join("tls-key.pem")).unwrap());
    let after = files::read_json(&private.join("deployment.json")).unwrap();
    for key in [
        "ledger_id",
        "owner_sid",
        "owner_account",
        "autostart",
        "runner_sha256",
    ] {
        assert_eq!(deployment[key], after[key]);
    }
    assert_eq!(
        config["backup_dir"],
        files::read_json(&private.join("service.json")).unwrap()["backup_dir"]
    );
    let wrong = f.root.join("unrelated");
    std::fs::create_dir(&wrong).unwrap();
    files::new_file(&wrong.join("business"), b"keep").unwrap();
    assert!(a::upgrade::apply(&wrong, &kit, &notices, true).is_err());
    assert_eq!(std::fs::read(wrong.join("business")).unwrap(), b"keep");
}

#[test]
#[cfg(not(windows))]
fn local_trust_update_preserves_existing_data_and_rejects_unrelated_signers() {
    use quote_host::files;
    use quote_ledger::{integrity, store};
    let f = Fixture::new();
    let private = f.root.join("private");
    let old = files::sha(&private.join("rust-service-host.exe")).unwrap();
    let config = json!({"schema":"777-host-v1","ledger_id":f.ledger,"backup_store_id":store::uid().unwrap(),"backup_dir":f.root.join("backup"),"bind":"192.168.4.23","port":8477,"certificate_sha256":quote_host::host::certificate_sha(&private.join("tls-cert.pem")).unwrap(),"private_security":{},"maintenance":false,"rust_host_sha256":old});
    files::replace_json(&private.join("service.json"), &config).unwrap();
    let deployment = json!({"schema":"777-site-deployment-v1","root":f.root,"owner_sid":"fixture-owner","machine":"fixture-machine","owner_account":"fixture-account","active_address":"192.168.4.23","port":8477,"ledger_id":f.ledger,"host_sha256":old,"runner_sha256":files::sha(&private.join("host-run.ps1")).unwrap(),"identity_sha256":files::sha(&private.join("host-identity.ps1")).unwrap(),"autostart":"fixture-existing-task"});
    files::replace_json(&private.join("deployment.json"), &deployment).unwrap();
    let state = f.root.join("local-signer.bin");
    let kit = f.root.join("trust.json");
    a::local_issuer::provision(&state, &kit, true).unwrap();
    let notices = private.join("rust-host-notices.txt");
    let inv = integrity::inventory(&store::open(&f.service.ledger, false).unwrap()).unwrap();
    let tls = files::sha(&private.join("tls-key.pem")).unwrap();
    a::registration::install(&f.root, &kit, &notices, true).unwrap();
    // Simulate a crash between exe replacement and service/deployment JSON publication.
    files::replace_json(&private.join("service.json"), &config).unwrap();
    files::replace_json(&private.join("deployment.json"), &deployment).unwrap();
    a::registration::install(&f.root, &kit, &notices, true).unwrap();
    a::registration::install(&f.root, &kit, &notices, true).unwrap();
    assert_eq!(
        inv,
        integrity::inventory(&store::open(&f.service.ledger, false).unwrap()).unwrap()
    );
    assert_eq!(tls, files::sha(&private.join("tls-key.pem")).unwrap());
    let after = files::read_json(&private.join("deployment.json")).unwrap();
    for key in [
        "ledger_id",
        "owner_sid",
        "owner_account",
        "autostart",
        "runner_sha256",
    ] {
        assert_eq!(deployment[key], after[key]);
    }
    assert_eq!(
        config["backup_dir"],
        files::read_json(&private.join("service.json")).unwrap()["backup_dir"]
    );
    assert!(!private.join("automatic-pair.bin").exists());
    let binding = std::fs::read(private.join("automatic-bootstrap.bin")).unwrap();
    let another = f.root.join("other-trust.json");
    a::local_issuer::provision(&f.root.join("other-signer.bin"), &another, true).unwrap();
    assert!(a::registration::install(&f.root, &another, &notices, true).is_err());
    assert!(binding == std::fs::read(private.join("automatic-bootstrap.bin")).unwrap());
    let wrong = f.root.join("unrelated");
    std::fs::create_dir(&wrong).unwrap();
    files::new_file(&wrong.join("business"), b"keep").unwrap();
    assert!(a::registration::install(&wrong, &kit, &notices, true).is_err());
    assert_eq!(std::fs::read(wrong.join("business")).unwrap(), b"keep");
}
