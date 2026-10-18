use crate::{Connection, DesktopError, Result};
pub fn build(c: &Connection) -> Result<reqwest::Client> {
    quote_security::tls::build(&quote_security::Connection {
        url: c.url.clone(),
        certificate_pem: c.certificate_pem.clone(),
        certificate_sha256: c.certificate_sha256.clone(),
    }).map_err(|e| DesktopError::new(e.status, &e.code))
}
