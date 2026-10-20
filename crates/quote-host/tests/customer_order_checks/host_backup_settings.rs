use super::*;
use quote_host::{backup_settings, daily_backup, files};
use std::path::PathBuf;
struct Locations(PathBuf);
impl Drop for Locations {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn setup(f: &mut Fixture) -> Locations {
    let base = std::env::temp_dir().join(format!("777-backup-settings-{}", store::uid().unwrap()));
    std::fs::create_dir(&base).unwrap();
    for name in ["normal", "next", "hidden"] {
        std::fs::create_dir(base.join(name)).unwrap();
    }
    let store_id = store::uid().unwrap();
    files::replace_json(
        &base.join("normal/777-backups.json"),
        &json!({"format":"777-backups-v1","store_id":store_id,"backups":[],"last_success":null}),
    )
    .unwrap();
    let ledger_id = integrity::inventory(&store::open(&f.s.ledger, false).unwrap()).unwrap()
        ["ledger_id"]
        .clone();
    f.s.config =
        json!({"ledger_id":ledger_id,"backup_store_id":store_id,"backup_dir":base.join("normal")});
    files::replace_json(&f.root.join("private/service.json"), &f.s.config).unwrap();
    daily_backup::configure(&f.s, &base.join("hidden"), 23).unwrap();
    Locations(base)
}
fn update(f: &mut Fixture, before: &Value, path: &std::path::Path, hour: u8) -> Value {
    f.post("/v1/developer/backup-settings",json!({"ledger_id":before["ledger_id"],"expected_revision":before["revision"],"backup_dir":path,"daily_hour":hour}))
}
#[test]
fn host_backup_settings_apply_to_live_scheduler_persist_and_retry_without_duplicate() {
    let mut f = Fixture::new();
    let dirs = setup(&mut f);
    let before = f.get("/v1/developer/backup-settings");
    let listing = f.post(
        "/v1/developer/backup-directories",
        json!({"ledger_id":before["ledger_id"],"path":dirs.0}),
    );
    assert!(listing["directories"]
        .as_array()
        .unwrap()
        .contains(&json!(dirs.0.join("next"))));
    std::fs::write(dirs.0.join("normal/keep.txt"), b"old backup remains").unwrap();
    let after = update(&mut f, &before, &dirs.0.join("next"), 0);
    assert_eq!(after["daily_hour"], 0);
    assert_eq!(after["hidden_dir"], before["hidden_dir"]);
    assert_ne!(after["revision"], before["revision"]);
    assert_eq!(update(&mut f, &before, &dirs.0.join("next"), 0), after);
    assert_eq!(f.get("/v1/backup")["target"], json!(dirs.0.join("next")));
    assert_eq!(daily_backup::config(&f.s).unwrap()["daily_hour"], 0);
    // Actual scheduler creates recovery data and readable Excel in the new location without restarting.
    let made = daily_backup::due(&f.s).unwrap().unwrap();
    assert!(made["backup_id"].is_string());
    assert!(daily_backup::due(&f.s).unwrap().is_none());
    let folder = std::fs::read_dir(dirs.0.join("next"))
        .unwrap()
        .filter_map(Result::ok)
        .map(|e| e.path())
        .find(|p| p.is_dir())
        .unwrap();
    assert!(folder.join("data.qbackup").is_file());
    assert!(folder.join("data.xlsx").is_file());
    assert_eq!(
        std::fs::read(dirs.0.join("normal/keep.txt")).unwrap(),
        b"old backup remains"
    );
    f.s.config = files::read_json(&f.root.join("private/service.json")).unwrap();
    assert_eq!(backup_settings::read(&f.s).unwrap(), after);
}
#[test]
fn host_backup_settings_reject_stale_foreign_invalid_and_packaged_requests() {
    let mut f = Fixture::new();
    let dirs = setup(&mut f);
    let before = f.get("/v1/developer/backup-settings");
    let payload = json!({"ledger_id":before["ledger_id"],"expected_revision":before["revision"],"backup_dir":dirs.0.join("next"),"daily_hour":0});
    let original = std::fs::read(f.root.join("private/service.json")).unwrap();
    for (field, value) in [
        ("ledger_id", json!(store::uid().unwrap())),
        ("expected_revision", json!("stale")),
        ("daily_hour", json!(24)),
        ("backup_dir", json!(f.root)),
        ("backup_dir", json!(dirs.0.join("hidden"))),
        ("backup_dir", json!(dirs.0)),
    ] {
        let mut bad = payload.clone();
        bad[field] = value;
        assert!(f
            .s
            .handle(
                "POST",
                "/v1/developer/backup-settings",
                &f.token,
                &bad,
                "",
                "test"
            )
            .is_err());
        assert_eq!(
            std::fs::read(f.root.join("private/service.json")).unwrap(),
            original
        );
    }
    let mut hidden = payload.clone();
    hidden["hidden_dir"] = json!("must not change");
    assert!(f
        .s
        .handle(
            "POST",
            "/v1/developer/backup-settings",
            &f.token,
            &hidden,
            "",
            "test"
        )
        .is_err());
    assert!(f
        .s
        .handle(
            "POST",
            "/v1/developer/backup-settings",
            "invalid-device-token",
            &payload,
            "",
            "test"
        )
        .is_err());
    let caps = quote_host::automatic::permissions::all();
    assert!(quote_host::automatic::permissions::authorize(
        &f.s,
        &caps,
        "POST",
        "/v1/developer/backup-settings",
        &payload
    )
    .is_err());
    f.post(
        "/v1/accounts",
        json!({"username":"sales","password":"fixture-sales-123","role":"sales"}),
    );
    let login =
        f.s.auth
            .login(&json!("sales"), &json!("fixture-sales-123"), "test")
            .unwrap();
    assert!(f
        .s
        .handle(
            "GET",
            "/v1/developer/backup-settings",
            login["token"].as_str().unwrap(),
            &Value::Null,
            "",
            "test"
        )
        .is_err());
}

#[test]
fn host_backup_time_can_change_while_backup_share_is_unavailable() {
    let mut f = Fixture::new();
    let dirs = setup(&mut f);
    let before = f.get("/v1/developer/backup-settings");
    std::fs::rename(dirs.0.join("normal"), dirs.0.join("disconnected")).unwrap();
    let after = update(&mut f, &before, &dirs.0.join("normal"), 8);
    assert_eq!(after["daily_hour"], 8);
    assert_eq!(after["backup_dir"], before["backup_dir"]);
    assert!(!dirs.0.join("normal").exists());
}
