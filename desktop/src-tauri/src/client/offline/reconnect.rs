//! Connectivity wakes only transient retry; it does not authenticate or bypass 429/403.
use super::*;
impl Desktop {
    pub(super) async fn reconnect_probe(&mut self) -> Result<()> {
        let p = self.automatic_package.as_ref().ok_or_else(context_error)?;
        let public = p
            .validate(crate::startup::delivery())
            .map_err(|_| context_error())?;
        let connection = Connection {
            url: public.url,
            certificate_pem: public.certificate_pem,
            certificate_sha256: public.certificate_sha256,
        };
        #[cfg(feature = "verification")]
        let connection = self.isolated_connection(connection)?;
        let url = reqwest::Url::parse(&connection.url).map_err(|_| context_error())?;
        let online = matches!(
            tokio::time::timeout(
                std::time::Duration::from_millis(500),
                tokio::net::TcpStream::connect((
                    url.host_str().ok_or_else(context_error)?,
                    url.port_or_known_default().ok_or_else(context_error)?
                ))
            )
            .await,
            Ok(Ok(_))
        );
        if self.last_tcp == Some(false) && online {
            self.automatic_retry.reconnected();
        }
        self.last_tcp = Some(online);
        Ok(())
    }
}
