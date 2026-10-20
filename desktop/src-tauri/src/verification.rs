//! Owned-profile IPC runner shared by runtime verification entries.
pub fn run() {
    use std::io::{BufRead, Write};
    let args = std::env::args().collect::<Vec<_>>();
    let index = args
        .iter()
        .position(|a| a == "--profile")
        .expect("isolated profile required");
    let root = std::path::PathBuf::from(args.get(index + 1).expect("profile path"));
    if !root.join("777-isolated-profile.json").is_file() {
        panic!("owned isolated profile marker required");
    }
    let mut client = crate::Desktop::new(root, !cfg!(windows)).expect("isolated client store");
    if let Some(index) = args.iter().position(|a| a == "--package") {
        client
            .load_automatic_package(std::path::Path::new(
                args.get(index + 1).expect("package path"),
            ))
            .expect("isolated package");
    }
    let runtime = tokio::runtime::Runtime::new().unwrap();
    if args.iter().any(|a| a == "--offline-worker") {
        runtime.block_on(async move {
            loop {
                let _ = client.sync_tick().await;
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            }
        });
        return;
    }
    for line in std::io::stdin().lock().lines() {
        let line = line.unwrap();
        let response = match serde_json::from_str::<crate::Action>(&line) {
            Ok(a) => match runtime.block_on(client.execute(a)) {
                Ok(v) => serde_json::json!({"ok":v}),
                Err(e) => serde_json::json!({"error":e}),
            },
            Err(_) => serde_json::json!({"error":{"status":422,"code":"INVALID_ACTION"}}),
        };
        println!("{}", response);
        std::io::stdout().flush().unwrap();
    }
}
