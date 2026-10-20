//! Explicit isolated loopback routing for real TLS tests. Never compiled into production.
use super::*;
impl Desktop {
    pub(crate) fn isolated_connection(&self, connection: Connection) -> Result<Connection> {
        let path = std::path::PathBuf::from(self.store.profile());
        let override_path = path.join("offline-test-connection.json");
        if !override_path.exists() {
            return Ok(connection);
        }
        if !path
            .canonicalize()
            .map_err(|_| context_error())?
            .starts_with(
                std::env::temp_dir()
                    .canonicalize()
                    .map_err(|_| context_error())?,
            )
            || std::fs::read(path.join("777-isolated-profile.json"))
                .ok()
                .and_then(|v| serde_json::from_slice::<Value>(&v).ok())
                != Some(json!({"production":false}))
        {
            return Err(context_error());
        }
        let override_connection: Connection =
            serde_json::from_slice(&std::fs::read(override_path).map_err(|_| context_error())?)
                .map_err(|_| context_error())?;
        let url = reqwest::Url::parse(&override_connection.url).map_err(|_| context_error())?;
        if url.scheme() != "https"
            || url.host_str() != Some("127.0.0.1")
            || override_connection.certificate_sha256 != connection.certificate_sha256
            || override_connection.certificate_pem != connection.certificate_pem
        {
            return Err(context_error());
        }
        tls::build(&override_connection)?;
        Ok(override_connection)
    }
}
