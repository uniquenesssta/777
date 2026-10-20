//! Developer maintenance of the connected Host; never the local launcher configuration.
use super::*;
impl Desktop {
    pub(super) async fn host_settings(&mut self, path: &str, body: Option<Value>) -> Result<Value> {
        connections::development()?;
        self.admin()?;
        if body.is_some() && self.has_pending()? {
            return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
        }
        self.request(
            if body.is_some() { "POST" } else { "GET" },
            path,
            body.as_ref(),
        )
        .await
    }
}
