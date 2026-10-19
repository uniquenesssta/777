//! Synthetic daily snapshot/delivery checks; no network share or Windows attributes.
use quote_host::{auth::Auth, daily_backup, query::Queries, service::Service};
use quote_ledger::store;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};
struct Fixture {
    base: PathBuf,
    s: Service,
    normal: PathBuf,
    hidden: PathBuf,
    token: String,
}
impl Fixture {
    fn new() -> Self {
        let base = std::env::temp_dir().join(format!("777-delivery-{}", store::uid().unwrap()));
        let root = base.join("host");
        let private = root.join("private");
        fs::create_dir_all(&private).unwrap();
        let normal = base.join("normal");
        fs::create_dir(&normal).unwrap();
        let ledger = private.join("ledger.sqlite3");
        let inventory = store::create(&ledger).unwrap();
        let backup_store = store::uid().unwrap();
        fs::write(normal.join("777-backups.json"),serde_json::to_vec(&json!({"format":"777-backups-v1","store_id":backup_store,"backups":[],"last_success":null})).unwrap()).unwrap();
        let mut auth = Auth::create(
            &private.join("auth.sqlite3"),
            "manager",
            "synthetic-secret-123",
        )
        .unwrap();
        let token = auth
            .login(&json!("manager"), &json!("synthetic-secret-123"), "test")
            .unwrap()["token"]
            .as_str()
            .unwrap()
            .into();
        let s = Service {
            root,
            config: json!({"ledger_id":inventory["ledger_id"],"backup_dir":normal,"backup_store_id":backup_store}),
            ledger,
            auth,
            devices: None,
            outputs: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: None,
        };
        let hidden = base.join("hidden");
        daily_backup::configure(&s, &hidden, 23).unwrap();
        Self {
            base,
            s,
            normal,
            hidden,
            token,
        }
    }
    fn status(&mut self) -> Value {
        self.s
            .handle("GET", "/v1/backup", &self.token, &Value::Null, "", "test")
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.base);
    }
}
#[test]
fn scheduler_silently_probes_and_resumes_the_original_pair_after_restart() {
    let mut f = Fixture::new();
    let offline = f.base.join("offline");
    fs::rename(&f.hidden, &offline).unwrap();
    let first = daily_backup::create(&f.s).unwrap();
    assert_eq!(first["delivery_complete"], false);
    let view = f.status();
    assert_eq!(view["delivery_state"], "partial");
    assert!(!view.to_string().contains("hidden"));
    assert!(!view.to_string().contains("PATH_UNAVAILABLE"));
    let folder = fs::read_dir(&f.normal)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.is_dir())
        .unwrap();
    let backup = fs::read(folder.join("data.qbackup")).unwrap();
    let excel = fs::read(folder.join("data.xlsx")).unwrap();
    quote_host::recovery::decode(&backup).unwrap();
    assert!(excel.starts_with(b"PK"));
    let state_path = f.s.root.join("private/daily-backups.json");
    let waiting = fs::read(&state_path).unwrap();
    // Opening auth anew and re-reading the on-disk queue models service restart.
    f.s.auth = Auth::open(f.s.root.join("private/auth.sqlite3")).unwrap();
    for _ in 0..3 {
        assert!(!daily_backup::check(&f.s).unwrap().ready());
        assert!(daily_backup::due(&f.s).unwrap().is_none());
        assert_eq!(fs::read(&state_path).unwrap(), waiting);
    }
    // The successful ordinary destination need not be online for hidden recovery.
    fs::rename(&f.normal, f.base.join("ordinary-away")).unwrap();
    fs::rename(offline, &f.hidden).unwrap();
    assert!(daily_backup::check(&f.s).unwrap().ready());
    let second = daily_backup::due(&f.s).unwrap().unwrap();
    assert_eq!(first["backup_id"], second["backup_id"]);
    assert_eq!(second["delivery_complete"], true);
    let hidden = f.hidden.join(folder.file_name().unwrap());
    assert_eq!(fs::read(hidden.join("data.qbackup")).unwrap(), backup);
    assert_eq!(fs::read(hidden.join("data.xlsx")).unwrap(), excel);
    assert_eq!(f.status()["delivery_state"], "complete");
    assert!(daily_backup::due(&f.s).unwrap().is_none());
}
#[test]
fn two_failed_destinations_cannot_publish_a_successful_backup_state() {
    let mut f = Fixture::new();
    fs::rename(&f.normal, f.base.join("offline-normal")).unwrap();
    fs::rename(&f.hidden, f.base.join("offline-hidden")).unwrap();
    assert!(daily_backup::create(&f.s).is_err());
    let state = f.status();
    assert_eq!(state["delivery_state"], "failed");
    assert_eq!(state["delivery_complete"], false);
    fs::rename(f.base.join("offline-normal"), &f.normal).unwrap();
    let normal_only = daily_backup::due(&f.s).unwrap().unwrap();
    assert_eq!(normal_only["delivery_complete"], false);
    fs::rename(f.base.join("offline-hidden"), &f.hidden).unwrap();
    let complete = daily_backup::due(&f.s).unwrap().unwrap();
    assert_eq!(normal_only["backup_id"], complete["backup_id"]);
    assert_eq!(complete["delivery_complete"], true);
}
