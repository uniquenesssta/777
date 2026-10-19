//! Real auxiliary subprocesses, no product installer or Windows task.
use serde_json::Value;
use std::{fs, path::PathBuf, process::Command};
#[test]
fn child_entry() {
    if std::env::var_os("Q777_DIAGNOSTIC_CHILD").is_none() {
        return;
    }
    quote_diagnostics::init("probe");
    quote_diagnostics::event(
        "probe",
        serde_json::json!({"phase":"waiting","secret":"NEVER_RECORD"}),
    );
    if std::env::var_os("Q777_DIAGNOSTIC_NESTED").is_none() {
        let result = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "child_entry"])
            .env("Q777_DIAGNOSTIC_NESTED", "1")
            .output()
            .unwrap();
        assert!(result.status.success());
    }
}
fn root(name: &str) -> PathBuf {
    let p = std::env::temp_dir().join(format!("777-log-{name}-{}", std::process::id()));
    fs::create_dir_all(&p).unwrap();
    p
}
#[test]
fn each_launch_has_one_folder_children_share_it_and_execution_is_linked() {
    let root = root("correlation");
    for _ in 0..2 {
        let result = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "child_entry"])
            .env("Q777_DIAGNOSTIC_CHILD", "1")
            .env("QUOTE777_LOG_ROOT", &root)
            .env("QUOTE777_EXECUTION_ID", "maintenance-operation")
            .env_remove("QUOTE777_LOG_SESSION")
            .env_remove("QUOTE777_LOG_DISABLED")
            .output()
            .unwrap();
        assert!(result.status.success());
    }
    let folders: Vec<_> = fs::read_dir(root.join("logs"))
        .unwrap()
        .map(|x| x.unwrap().path())
        .collect();
    assert_eq!(folders.len(), 2);
    for folder in folders {
        assert_eq!(fs::read_dir(&folder).unwrap().count(), 2);
        let raw = fs::read_to_string(folder.join("runtime.jsonl")).unwrap();
        assert!(!raw.contains("NEVER_RECORD"));
        let rows: Vec<Value> = raw
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect();
        assert_eq!(rows.iter().filter(|r| r["event"] == "probe").count(), 2);
        assert!(rows
            .iter()
            .all(|r| r["execution_id"] == "maintenance-operation"));
    }
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn disabled_formal_backend_creates_no_log_directory_even_with_errors_and_children() {
    let root = root("disabled");
    let result = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "child_entry"])
        .env("Q777_DIAGNOSTIC_CHILD", "1")
        .env("QUOTE777_LOG_ROOT", &root)
        .env("QUOTE777_LOG_DISABLED", "1")
        .output()
        .unwrap();
    assert!(result.status.success());
    assert!(!root.join("logs").exists());
    fs::remove_dir_all(root).unwrap();
}
