//! Test driver for the actual debug-only IPC parser/client; never a release entry.
#[cfg(all(
    debug_assertions,
    not(any(feature = "manager", feature = "sales", feature = "verification"))
))]
fn main() {
    use std::io::{BufRead, Write};
    let root = std::path::PathBuf::from(std::env::args().nth(1).expect("isolated profile"));
    let marker: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join("777-isolated-profile.json")).unwrap())
            .unwrap();
    assert_eq!(marker, serde_json::json!({"production":false}));
    assert!(root
        .canonicalize()
        .unwrap()
        .starts_with(std::env::temp_dir().canonicalize().unwrap()));
    let mut desktop = quote_desktop::Desktop::new(root, !cfg!(windows)).unwrap();
    let runtime = tokio::runtime::Runtime::new().unwrap();
    for line in std::io::stdin().lock().lines() {
        let response = match serde_json::from_str::<quote_desktop::Action>(&line.unwrap()) {
            Ok(action) => match runtime.block_on(desktop.execute(action)) {
                Ok(value) => serde_json::json!({"ok":value}),
                Err(error) => serde_json::json!({"error":error}),
            },
            Err(_) => serde_json::json!({"error":{"code":"INVALID_ACTION"}}),
        };
        println!("{response}");
        std::io::stdout().flush().unwrap();
    }
}
#[cfg(not(all(
    debug_assertions,
    not(any(feature = "manager", feature = "sales", feature = "verification"))
)))]
fn main() {
    panic!("DEBUG_DEVELOPMENT_ONLY");
}
