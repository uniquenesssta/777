fn main() {
    println!("cargo:rustc-check-cfg=cfg(quote777_packaged)");
    for key in [
        "QUOTE777_PACKAGE_DELIVERY",
        "QUOTE777_PACKAGE_CONNECTION",
        "QUOTE777_PACKAGE_METADATA",
    ] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    if let Ok(kind) = std::env::var("QUOTE777_PACKAGE_DELIVERY") {
        assert!(
            matches!(kind.as_str(), "manager" | "sales"),
            "INVALID_PACKAGE_DELIVERY"
        );
        let feature = format!("CARGO_FEATURE_{}", kind.to_uppercase());
        assert!(
            std::env::var_os(feature).is_some(),
            "PACKAGE_FEATURE_MISMATCH"
        );
        assert!(
            std::env::var_os("CARGO_FEATURE_VERIFICATION").is_none(),
            "PACKAGE_VERIFICATION_FORBIDDEN"
        );
        assert_eq!(
            std::env::var("PROFILE").as_deref(),
            Ok("release"),
            "PACKAGE_RELEASE_REQUIRED"
        );
        let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").expect("OUT_DIR"));
        for (key, name) in [
            ("QUOTE777_PACKAGE_CONNECTION", "package-connection.json"),
            ("QUOTE777_PACKAGE_METADATA", "package-metadata.json"),
        ] {
            let input = std::env::var(key).expect("PACKAGE_INPUT_REQUIRED");
            println!("cargo:rerun-if-changed={input}");
            std::fs::copy(input, output.join(name)).expect("copy validated package input");
        }
        println!("cargo:rustc-cfg=quote777_packaged");
    }
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
