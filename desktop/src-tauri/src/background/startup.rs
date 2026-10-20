//! Per-user startup registration and detached native process launch.
use super::*;
use std::{
    os::windows::process::CommandExt,
    process::{Command, Stdio},
};
/// The installed executable is the only startup target; no shell or copied SDK.
pub fn ensure() -> Result<()> {
    if !crate::startup::formal() {
        return Ok(());
    }
    let exe = std::env::current_exe().map_err(|_| failure())?;
    let name = format!("Quote777-{}-Sync", crate::delivery());
    register(&exe, &name)?;
    Command::new(exe)
        .arg("--background-sync")
        .creation_flags(0x08000000)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| failure())?;
    Ok(())
}

fn register(exe: &std::path::Path, name: &str) -> Result<()> {
    let command = format!("\"{}\" --background-sync", exe.display());
    let result = Command::new("reg.exe")
        .args([
            "ADD",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "/v",
            name,
            "/t",
            "REG_SZ",
            "/d",
            &command,
            "/f",
        ])
        .creation_flags(0x08000000)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|_| failure())?;
    if !result.success() {
        return Err(failure());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct OwnedValue(String);
    impl Drop for OwnedValue {
        fn drop(&mut self) {
            let _ = Command::new("reg.exe")
                .args([
                    "DELETE",
                    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                    "/v",
                    &self.0,
                    "/f",
                ])
                .creation_flags(0x08000000)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
    #[test]
    fn owned_run_value_roundtrip_preserves_spaces_and_background_argument() {
        let name = OwnedValue(format!("Quote777-test-{}", crate::types::new_id().unwrap()));
        let exe = std::env::temp_dir().join("quote777 isolated desktop entry.exe");
        register(&exe, &name.0).unwrap();
        let result = Command::new("reg.exe")
            .args([
                "QUERY",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v",
                &name.0,
            ])
            .creation_flags(0x08000000)
            .output()
            .unwrap();
        assert!(result.status.success());
        assert!(String::from_utf8_lossy(&result.stdout)
            .contains(&format!("\"{}\" --background-sync", exe.display())));
    }
}
