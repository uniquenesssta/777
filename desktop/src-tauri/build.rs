fn main() {
    #[cfg(windows)]
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["desktop_action"])),
    )
    .expect("Tauri desktop build configuration");
}
