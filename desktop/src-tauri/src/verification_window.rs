//! Only compiled for isolated verification builds (and their parser tests).
use std::{io, path::PathBuf};

pub struct WindowProfile {
    pub root: PathBuf,
    pub debug_port: u16,
}

impl WindowProfile {
    pub fn from_args(args: &[String]) -> io::Result<Option<Self>> {
        if args.is_empty() {
            return Ok(None);
        }
        let invalid = || io::Error::other("ISOLATED_WINDOW_ARGUMENTS_REQUIRED");
        if args.len() != 5
            || args[0] != "--verification-window"
            || args[1] != "--profile"
            || args[3] != "--debug-port"
        {
            return Err(invalid());
        }
        let root = PathBuf::from(&args[2]);
        let debug_port = args[4].parse::<u16>().map_err(|_| invalid())?;
        if debug_port == 0 || !root.is_absolute() || root.file_name().is_none_or(|v| v != "desktop")
        {
            return Err(invalid());
        }
        let canonical = root.canonicalize()?;
        let parent = canonical.parent().ok_or_else(invalid)?;
        if parent.parent() != Some(std::env::temp_dir().canonicalize()?.as_path())
            || parent
                .file_name()
                .is_none_or(|v| !v.to_string_lossy().starts_with("777-p06-native-host-"))
        {
            return Err(invalid());
        }
        let marker: serde_json::Value =
            serde_json::from_slice(&std::fs::read(root.join("777-isolated-profile.json"))?)?;
        if marker != serde_json::json!({"production": false}) {
            return Err(invalid());
        }
        Ok(Some(Self { root, debug_port }))
    }

    pub fn data_directory(&self) -> PathBuf {
        self.root.join("webview2")
    }

    pub fn browser_args(&self) -> String {
        // Preserve wry 0.57.0's default switches when supplying explicit arguments.
        format!("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --remote-debugging-port={} --remote-debugging-address=127.0.0.1", self.debug_port)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let mut random = [0u8; 12];
            getrandom::getrandom(&mut random).unwrap();
            let name = random
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>();
            let root = std::env::temp_dir().join(format!("777-p06-native-host-{name}"));
            std::fs::create_dir_all(root.join("desktop")).unwrap();
            std::fs::write(
                root.join("desktop/777-isolated-profile.json"),
                r#"{"production":false}"#,
            )
            .unwrap();
            Self(root)
        }
        fn args(&self) -> Vec<String> {
            vec![
                "--verification-window".into(),
                "--profile".into(),
                self.0.join("desktop").to_string_lossy().into_owned(),
                "--debug-port".into(),
                "49152".into(),
            ]
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn normal_launch_has_no_verification_settings() {
        assert!(WindowProfile::from_args(&[]).unwrap().is_none());
    }

    #[test]
    fn marked_temp_profile_has_fixed_api_arguments_and_private_data_directory() {
        let fixture = Fixture::new();
        let value = WindowProfile::from_args(&fixture.args()).unwrap().unwrap();
        assert_eq!(value.root, fixture.0.join("desktop"));
        assert_eq!(value.data_directory(), fixture.0.join("desktop/webview2"));
        assert_eq!(value.browser_args(), "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --remote-debugging-port=49152 --remote-debugging-address=127.0.0.1");
    }

    #[test]
    fn invalid_ports_unknown_switches_and_relative_profiles_are_refused() {
        let fixture = Fixture::new();
        for port in ["0", "65536", "-1", "9222 --no-sandbox", ""] {
            let mut args = fixture.args();
            args[4] = port.into();
            assert!(WindowProfile::from_args(&args).is_err());
        }
        let mut args = fixture.args();
        args.push("--no-sandbox".into());
        assert!(WindowProfile::from_args(&args).is_err());
        args = fixture.args();
        args[2] = "desktop".into();
        assert!(WindowProfile::from_args(&args).is_err());
    }

    #[test]
    fn production_marker_missing_marker_and_nonfixture_root_are_refused() {
        let fixture = Fixture::new();
        let marker = fixture.0.join("desktop/777-isolated-profile.json");
        std::fs::write(&marker, r#"{"production":true}"#).unwrap();
        assert!(WindowProfile::from_args(&fixture.args()).is_err());
        std::fs::remove_file(&marker).unwrap();
        assert!(WindowProfile::from_args(&fixture.args()).is_err());
        let mut args = fixture.args();
        args[2] = std::env::temp_dir().to_string_lossy().into_owned();
        assert!(WindowProfile::from_args(&args).is_err());
    }
}
