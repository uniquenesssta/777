//! Persist the selected source and its mode in one atomic record.
use super::*;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    mode: String,
    connection: Connection,
}
impl Desktop {
    pub(super) fn saved_connection(&self) -> Result<Option<Connection>> {
        if let Some(source) = self.store.read::<Source>("current-source.bin")? {
            return Ok(Some(source.connection));
        }
        self.store.read("connection.bin")
    }
    pub(super) fn host_selected(&self) -> Result<bool> {
        if let Some(source) = self.store.read::<Source>("current-source.bin")? {
            return Ok(source.mode == "host");
        }
        Ok(self
            .store
            .read::<String>("data-source-mode.bin")?
            .as_deref()
            == Some("host"))
    }
    pub(super) fn remember_source(&self, mode: &str, connection: Connection) -> Result<()> {
        self.store.replace(
            "current-source.bin",
            &Source {
                mode: mode.into(),
                connection,
            },
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn source_mode_and_connection_reload_together_without_replacing_package_target() {
        let root = std::env::temp_dir().join(format!("777-source-{}", new_id().unwrap()));
        let desktop = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        let connection = Connection {
            url: "https://host.example:8477".into(),
            certificate_pem: "public".into(),
            certificate_sha256: "a".repeat(64),
        };
        desktop
            .store
            .write("package-target.bin", &json!({"ledger":"unchanged"}))
            .unwrap();
        let target = std::fs::read(root.join("package-target.bin")).unwrap();
        desktop.remember_source("host", connection.clone()).unwrap();
        drop(desktop);
        let desktop = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        assert!(desktop.host_selected().unwrap());
        assert_eq!(
            desktop.saved_connection().unwrap().unwrap().url,
            connection.url
        );
        desktop
            .remember_source(
                "local",
                Connection {
                    url: "https://127.0.0.1:18477".into(),
                    ..connection
                },
            )
            .unwrap();
        drop(desktop);
        let desktop = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        assert!(!desktop.host_selected().unwrap());
        assert_eq!(
            desktop.saved_connection().unwrap().unwrap().url,
            "https://127.0.0.1:18477"
        );
        assert_eq!(
            std::fs::read(root.join("package-target.bin")).unwrap(),
            target
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
