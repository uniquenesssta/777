//! Native-only deployment material. None of the secrets cross IPC.
use crate::{Connection, DesktopError, Result};
use serde::{Deserialize, Serialize};
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Bootstrap {
    pub schema: String,
    pub delivery: String,
    pub connection: Connection,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ticket: Option<String>,
}
impl Bootstrap {
    pub fn validate(&self, kind: &str) -> Result<()> {
        if self.schema != "777-desktop-bootstrap-v1" || self.delivery != kind {
            return Err(DesktopError::new(403, "DELIVERY_ROLE_MISMATCH"));
        }
        crate::tls::build(&self.connection)?;
        if kind != "development"
            && (self.username.is_some()
                || self.password.is_some()
                || self.ticket.as_ref().is_none_or(|s| s.len() != 43))
        {
            return Err(DesktopError::new(422, "DEPLOYMENT_NOT_CONFIGURED"));
        }
        if kind == "development"
            && (self.username.is_none()
                || self.password.is_none()
                || !self.connection.url.starts_with("https://127.0.0.1:"))
        {
            return Err(DesktopError::new(422, "INVALID_DEVELOPMENT_CONFIG"));
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Credential {
    pub config: Bootstrap,
    pub device_id: String,
    pub secret: String,
    pub profile: String,
}
pub fn delivery() -> &'static str {
    if cfg!(feature = "manager") {
        "manager"
    } else if cfg!(feature = "sales") {
        "sales"
    } else {
        "development"
    }
}
pub fn formal() -> bool {
    delivery() != "development"
}
