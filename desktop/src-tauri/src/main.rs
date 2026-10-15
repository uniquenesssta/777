#[cfg(windows)]
mod directory_dialog;

#[cfg(all(feature = "verification", any(windows, test)))]
mod verification_window;

#[cfg(windows)]
mod shell {
    use quote_desktop::{Action, Desktop, DesktopError};
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };
    use tauri::{Emitter, Manager, State};
    struct ClientState {
        desktop: tokio::sync::Mutex<Desktop>,
        writes: AtomicUsize,
    }
    type Shared = Arc<ClientState>;
    struct Writing<'a>(&'a AtomicUsize);
    impl<'a> Writing<'a> {
        fn start(value: &'a AtomicUsize) -> Self {
            value.fetch_add(1, Ordering::SeqCst);
            Self(value)
        }
    }
    impl Drop for Writing<'_> {
        fn drop(&mut self) {
            self.0.fetch_sub(1, Ordering::SeqCst);
        }
    }
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
        if let Action::PickDirectory { ref target } = request {
            let initial = state.desktop.lock().await.directory_context(target).await?;
            let owner = window
                .hwnd()
                .map_err(|_| DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE"))?
                .0 as isize;
            let selected =
                tokio::task::spawn_blocking(move || crate::directory_dialog::pick(owner, &initial))
                    .await
                    .map_err(|_| DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE"))??;
            return Ok(serde_json::json!({"directory":selected}));
        }
        let _writing = request
            .protects_close()
            .then(|| Writing::start(&state.writes));
        state.desktop.lock().await.execute(request).await
    }
    pub fn run() {
        #[cfg(feature = "verification")]
        let isolated = crate::verification_window::WindowProfile::from_args(
            &std::env::args().skip(1).collect::<Vec<_>>(),
        )
        .expect("isolated verification window arguments");
        let context = context();
        #[cfg(feature = "verification")]
        let context = {
            let mut context = context;
            if isolated.is_some() {
                let windows = &mut context.config_mut().app.windows;
                assert!(windows.len() == 1 && windows[0].label == "main");
                windows[0].create = false;
            }
            context
        };
        tauri::Builder::default()
            .setup(move |app| {
                let root = app.path().app_local_data_dir()?;
                let root = match quote_desktop::delivery() {
                    "manager"=>root.join("manager"),"sales"=>root.join("sales"),
                    _ if cfg!(debug_assertions) => std::env::var_os("LOCALAPPDATA")
                        .map(std::path::PathBuf::from)
                        .ok_or_else(|| std::io::Error::other("LOCALAPPDATA_REQUIRED"))?
                        .join("Quote777Development/desktop"),
                    _=>root,
                };
                #[cfg(feature = "verification")]
                let root = isolated.as_ref().map_or(root, |v| v.root.clone());
                let client =
                    Desktop::new(root, false).map_err(|e| std::io::Error::other(e.code))?;
                app.manage(Arc::new(ClientState { desktop: tokio::sync::Mutex::new(client), writes: AtomicUsize::new(0) }));
                #[cfg(feature = "verification")]
                if let Some(profile) = isolated {
                    let config = &app.config().app.windows[0];
                    tauri::WebviewWindowBuilder::from_config(app, config)?
                        .data_directory(profile.data_directory())
                        .additional_browser_args(&profile.browser_args())
                        .build()?;
                    println!("{}", serde_json::json!({"verification_window": "created", "browser_arguments_source": "WebView2_API", "debug_port": profile.debug_port, "data_directory": profile.data_directory()}));
                }
                Ok(())
            })
            .invoke_handler(tauri::generate_handler![desktop_action])
            .on_window_event(|window, event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    let s = window.state::<Shared>();
                    if s.writes.load(Ordering::SeqCst) != 0 {
                        api.prevent_close();
                        let _ = window.emit("close-blocked", ());
                    }
                }
            })
            .run(context)
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
