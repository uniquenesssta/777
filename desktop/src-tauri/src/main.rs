#[cfg(windows)]
mod shell {
    use quote_desktop::{Action, Desktop, DesktopError};
    use std::sync::Arc;
    use tauri::{Emitter, Manager, State};
    type Shared = Arc<tokio::sync::Mutex<Desktop>>;
    fn context() -> tauri::Context<tauri::Wry> {
        tauri::generate_context!()
    }
    #[cfg(feature = "verification")]
    pub fn build_info() -> serde_json::Value {
        use sha2::{Digest, Sha256};
        let context = context();
        let assets = context.assets();
        let index = assets.get(&"index.html".into());
        let html = index
            .as_ref()
            .map(|bytes| String::from_utf8_lossy(bytes))
            .unwrap_or_default();
        let names = assets
            .iter()
            .map(|(name, _)| name.into_owned())
            .collect::<Vec<_>>();
        serde_json::json!({
            "windows": true,
            "release": !cfg!(debug_assertions),
            "custom_protocol": !tauri::is_dev(),
            "tauri_is_dev": tauri::is_dev(),
            "embedded_index": index.as_ref().is_some_and(|bytes| !bytes.is_empty()),
            "entry_js": names.iter().any(|name| name.ends_with(".js") && html.contains(name.as_str())),
            "entry_css": names.iter().any(|name| name.ends_with(".css") && html.contains(name.as_str())),
            "asset_count": names.len(),
            "asset_names": names,
            "index_sha256": index.as_ref().map(|bytes| format!("{:x}", Sha256::digest(bytes))),
        })
    }
    #[tauri::command]
    async fn desktop_action(
        window: tauri::WebviewWindow,
        state: State<'_, Shared>,
        request: Action,
    ) -> Result<serde_json::Value, DesktopError> {
        if window.label() != "main" {
            return Err(DesktopError::new(403, "WINDOW_NOT_AUTHORIZED"));
        }
        state.lock().await.execute(request).await
    }
    pub fn run() {
        tauri::Builder::default()
            .setup(|app| {
                let root = app.path().app_local_data_dir()?;
                #[cfg(feature = "verification")]
                let root = {
                    let args = std::env::args().collect::<Vec<_>>();
                    if args.iter().any(|a| a == "--verification-window") {
                        let i = args
                            .iter()
                            .position(|a| a == "--profile")
                            .ok_or_else(|| std::io::Error::other("ISOLATED_PROFILE_REQUIRED"))?;
                        let p =
                            std::path::PathBuf::from(args.get(i + 1).ok_or_else(|| {
                                std::io::Error::other("ISOLATED_PROFILE_REQUIRED")
                            })?);
                        if !p.join("777-isolated-profile.json").is_file() {
                            return Err(std::io::Error::other("ISOLATED_PROFILE_REQUIRED").into());
                        }
                        p
                    } else {
                        root
                    }
                };
                let client =
                    Desktop::new(root, false).map_err(|e| std::io::Error::other(e.code))?;
                app.manage(Arc::new(tokio::sync::Mutex::new(client)));
                Ok(())
            })
            .invoke_handler(tauri::generate_handler![desktop_action])
            .on_window_event(|window, event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    let s = window.state::<Shared>();
                    if s.try_lock().is_err() {
                        api.prevent_close();
                        let _ = window.emit("close-blocked", ());
                    }
                }
            })
            .run(context())
            .expect("Windows desktop host failed");
    }
}
fn main() {
    #[cfg(feature = "verification")]
    if std::env::args().any(|a| a == "--verification-build-info") {
        #[cfg(windows)]
        println!("{}", shell::build_info());
        #[cfg(not(windows))]
        println!("{{\"windows\":false,\"scope\":\"actual Windows inspection required\"}}");
        return;
    }
    #[cfg(feature = "verification")]
    if std::env::args().any(|a| a == "--verification-bridge") {
        verification_bridge();
        return;
    }
    #[cfg(windows)]
    shell::run();
    #[cfg(not(windows))]
    {
        eprintln!("ACTUAL_WINDOWS_REQUIRED");
        std::process::exit(1);
    }
}
#[cfg(feature = "verification")]
fn verification_bridge() {
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
    let mut client =
        quote_desktop::Desktop::new(root, !cfg!(windows)).expect("isolated client store");
    let runtime = tokio::runtime::Runtime::new().unwrap();
    for line in std::io::stdin().lock().lines() {
        let line = line.unwrap();
        let response = match serde_json::from_str::<quote_desktop::Action>(&line) {
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
