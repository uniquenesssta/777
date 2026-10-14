fn main() {
    #[cfg(windows)]
    {
        if std::env::var("PROFILE").as_deref() == Ok("release") && tauri_build::is_dev() {
            panic!("WINDOWS_RELEASE_REQUIRES_EMBEDDED_FRONTEND: enable custom-protocol or use tauri build");
        }
        tauri_build::try_build(
            tauri_build::Attributes::new()
                .app_manifest(tauri_build::AppManifest::new().commands(&["desktop_action"])),
        )
        .expect("Tauri desktop build configuration");
    }
}
