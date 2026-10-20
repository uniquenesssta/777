#![cfg_attr(
    all(windows, not(debug_assertions), not(feature = "verification")),
    windows_subsystem = "windows"
)]

#[cfg(windows)]
mod directory_dialog;

#[cfg(all(any(feature = "verification", debug_assertions), any(windows, test)))]
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
        background: std::sync::atomic::AtomicBool,
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
        let context = tauri::generate_context!();
        if let Some(font) = context.assets().get(&"fonts/NotoSansSC-VF.ttf".into()) {
            if let Err(e) = quote_desktop::configure_export_font(font.as_ref()) {
                quote_diagnostics::event(
                    "desktop.output.font_unavailable",
                    serde_json::json!({"error":e.code}),
                );
            }
        }
        context
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
        request: serde_json::Value,
    ) -> Result<serde_json::Value, DesktopError> {
        if window.label() != "main" {
            return Err(DesktopError::new(403, "WINDOW_NOT_AUTHORIZED"));
        }
        let request = Action::from_request(request)?;
        if let Action::PickDirectory { ref target } = request {
            let initial = state.desktop.lock().await.directory_context(target).await?;
            // directory_context authorizes the exact target before showing any dialog.
            let local = [
                "developer_root",
                "developer_backup",
                "developer_output",
                "developer_hidden",
                "developer_restore",
                "developer_recovery_file",
            ]
            .contains(&target.as_str());
            let owner = window
                .hwnd()
                .map_err(|_| DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE"))?
                .0 as isize;
            let file = [
                "developer_recovery_file",
                "public_connection",
                "device_enrollment",
            ]
            .contains(&target.as_str());
            let title = match target.as_str() {
                "public_connection" => "选择 Host 公开连接文件",
                "device_enrollment" => "选择桌面设备登记文件",
                "developer_recovery_file" => "选择 .qbackup 恢复文件",
                _ => "选择保存文件夹",
            };
            let selected = tokio::task::spawn_blocking(move || {
                crate::directory_dialog::pick(owner, &initial, local, file, title)
            })
            .await
            .map_err(|_| DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE"))??;
            return Ok(serde_json::json!({"directory":selected}));
        }
        let _writing = request
            .protects_close()
            .then(|| Writing::start(&state.writes));
        let mut desktop = state.desktop.lock().await;
        let result = desktop.execute(request).await;
        let ready = desktop.background_ready();
        drop(desktop);
        if ready && !state.background.swap(true, Ordering::SeqCst) {
            #[cfg(quote777_packaged)]
            if quote_desktop::background::ensure().is_err() {
                state.background.store(false, Ordering::SeqCst);
            }
        }
        result
    }
    pub fn run() {
        #[cfg(any(feature = "verification", debug_assertions))]
        let isolated = crate::verification_window::WindowProfile::from_args(
            &std::env::args().skip(1).collect::<Vec<_>>(),
        )
        .expect("isolated verification window arguments");
        let mut context = context();
        if quote_desktop::delivery() != "development" {
            context.config_mut().app.windows[0].create = false;
        }
        #[cfg(any(feature = "verification", debug_assertions))]
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
                    "manager" | "sales" => quote_desktop::formal_profile_root(
                        &std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA")
                            .ok_or_else(|| std::io::Error::other("LOCALAPPDATA_REQUIRED"))?)
                    ).expect("formal profile"),
                    _ if cfg!(debug_assertions) => std::env::var_os("LOCALAPPDATA")
                        .map(std::path::PathBuf::from)
                        .ok_or_else(|| std::io::Error::other("LOCALAPPDATA_REQUIRED"))?
                        .join("Quote777Development/desktop"),
                    _=>root,
                };
                #[cfg(any(feature = "verification", debug_assertions))]
                let root = isolated.as_ref().map_or(root, |v| v.root.clone());
                let user_data = root.join("webview2");
                let client =
                    Desktop::new(root, false).map_err(|e| std::io::Error::other(e.code))?;
                #[cfg(quote777_packaged)]
                let client={
                  let mut client=client;
                  if quote_desktop::package_info()["device_protocol"]=="777-auto-enrollment-v1" {
                    // A failure is retried silently at bootstrap; no login/file dialog fallback.
                    if let Err(e)=client.load_automatic_package(&app.path().resource_dir()?.join("automatic/package.json")) {
                        quote_diagnostics::event("automatic.package.unavailable",serde_json::json!({"error":e.code}));
                    }
                  }
                  client
                };
                if client.background_ready() {
                    #[cfg(quote777_packaged)]
                    let _=quote_desktop::background::ensure();
                }
                app.manage(Arc::new(ClientState { desktop: tokio::sync::Mutex::new(client), writes: AtomicUsize::new(0), background: std::sync::atomic::AtomicBool::new(false) }));
                #[cfg(any(feature = "verification", debug_assertions))]
                let isolated_created = if let Some(profile) = isolated {
                    let config = &app.config().app.windows[0];
                    tauri::WebviewWindowBuilder::from_config(app, config)?
                        .data_directory(profile.data_directory())
                        .additional_browser_args(&profile.browser_args())
                        .build()?;
                    println!("{}", serde_json::json!({"verification_window": "created", "browser_arguments_source": "WebView2_API", "debug_port": profile.debug_port, "data_directory": profile.data_directory()}));
                    true
                } else { false };
                #[cfg(not(any(feature = "verification", debug_assertions)))]
                let isolated_created = false;
                if quote_desktop::delivery() != "development" && !isolated_created {
                    tauri::WebviewWindowBuilder::from_config(app, &app.config().app.windows[0])?
                        .data_directory(user_data)
                        .build()?;
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
    #[cfg(all(windows, quote777_packaged))]
    if std::env::args().any(|a| a == "--background-sync") {
        let _ = quote_desktop::background::run();
        return;
    }
    if quote_desktop::delivery() == "development" {
        quote_diagnostics::init("desktop");
    }
    #[cfg(all(windows, quote777_packaged))]
    if std::env::args().any(|a| a == "--package-info") {
        let mut info = quote_desktop::package_info();
        info["custom_protocol"] = serde_json::json!(!tauri::is_dev());
        println!("{info}");
        return;
    }
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
    {
        shell::run();
        quote_diagnostics::event("runtime.stop", serde_json::json!({"ok":true}));
    }
    #[cfg(not(windows))]
    {
        eprintln!("ACTUAL_WINDOWS_REQUIRED");
        std::process::exit(1);
    }
}
#[cfg(feature = "verification")]
fn verification_bridge() {
    quote_desktop::run_verification_bridge();
}
