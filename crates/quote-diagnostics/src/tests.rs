use super::*;
use crate::storage::LIMIT;
use std::fs;
#[test]
fn repeated_events_are_counted_without_flooding() {
    let directory = std::env::temp_dir().join(format!("777-log-flood-{}", std::process::id()));
    let _ = LOGGER.set(Mutex::new(Logger {
        directory: directory.clone(),
        component: "test".into(),
        execution_id: "test-operation".into(),
        recent: HashMap::new(),
    }));
    for _ in 0..10000 {
        event("failure", json!({"code":"PATH_UNAVAILABLE"}));
    }
    event_each("save", json!({"status":"ok"}));
    event_each("save", json!({"status":"ok"}));
    event("runtime.stop", json!({}));
    let raw = fs::read_to_string(directory.join("runtime.jsonl")).unwrap();
    let rows: Vec<Value> = raw
        .lines()
        .map(|v| serde_json::from_str(v).unwrap())
        .collect();
    assert_eq!(rows.len(), 5);
    assert_eq!(rows[1]["event"], "save");
    assert_eq!(rows[2]["event"], "save");
    assert_eq!(rows[3]["fields"]["suppressed"], 9999);
    fs::remove_dir_all(directory).unwrap();
}
#[test]
fn rotates_only_owned_logs_and_preserves_json() {
    let directory = std::env::temp_dir().join(format!("777-log-test-{}", std::process::id()));
    fs::create_dir_all(&directory).unwrap();
    fs::write(directory.join("unrelated.txt"), b"keep").unwrap();
    let logger = Logger {
        directory: directory.clone(),
        component: "test".into(),
        execution_id: "test-operation".into(),
        recent: HashMap::new(),
    };
    for _ in 0..6 {
        fs::write(directory.join("runtime.jsonl"), vec![b' '; LIMIT as usize]).unwrap();
        logger
            .write("test.error", json!({"path":"\\\\server\\共享","os_code":5}))
            .unwrap();
    }
    assert!(directory.join("runtime.2.jsonl").exists());
    assert!(!directory.join("runtime.3.jsonl").exists());
    assert_eq!(fs::read(directory.join("unrelated.txt")).unwrap(), b"keep");
    let record: Value =
        serde_json::from_slice(&fs::read(directory.join("runtime.jsonl")).unwrap()).unwrap();
    assert_eq!(record["fields"]["os_code"], 5);
    fs::remove_dir_all(directory).unwrap();
}
