//! Native local-first adapter. Existing IPC and formal presentation stay unchanged.
mod actions;
mod downloads;
mod enrollment;
mod history;
mod reconnect;
mod synchronize;
#[cfg(feature = "verification")]
mod verification;
use super::*;
const FORMAT: &str = "777-offline-order-v1";
fn context_error() -> DesktopError {
    DesktopError::new(409, "OFFLINE_IDENTITY_UNAVAILABLE")
}
impl Desktop {
    pub fn offline_ready(&self) -> bool {
        crate::startup::formal() && self.local.active().unwrap_or(false)
    }
    pub fn background_ready(&self) -> bool {
        crate::startup::formal()
            && self.automatic_package.is_some()
            && (self.auto_expires > 0 || self.offline_ready())
    }
    pub(super) fn local_bootstrap(&mut self) -> Result<Value> {
        let p = self.automatic_package.as_ref().ok_or_else(context_error)?;
        let connection = p
            .validate(crate::startup::delivery())
            .map_err(|_| context_error())?;
        let ctx = self.local_context()?;
        let b = &ctx["binding"];
        if b["package"] != p.manifest["package_id"]
            || b["role"]
                != if crate::startup::delivery() == "manager" {
                    "admin"
                } else {
                    "sales"
                }
            || b["capabilities"] != p.manifest["capabilities"]
            || b["ledger"] != p.profile["ledger_id"]
            || b["site"] != p.profile["site_id"]
            || b["pin"] != connection.certificate_sha256
        {
            return Err(context_error());
        }
        let connection = Connection {
            url: connection.url,
            certificate_pem: connection.certificate_pem,
            certificate_sha256: connection.certificate_sha256,
        };
        #[cfg(feature = "verification")]
        let connection = self.isolated_connection(connection)?;
        self.session = Some(Session {
            http: tls::build(&connection)?,
            connection,
            token: String::new(),
            subject: b["subject"].as_str().ok_or_else(context_error)?.into(),
            role: b["role"].as_str().ok_or_else(context_error)?.into(),
        });
        Ok(
            json!({"delivery":crate::startup::delivery(),"automatic":true,"session":{"subject":b["subject"],"role":b["role"],"username":"","pending":self.has_pending()?,"ledger_id":b["ledger"],"pricing_mode_version":"final-unit-v1"}}),
        )
    }
    pub(in crate::client) fn local_context(&self) -> Result<Value> {
        let p = self.automatic_package.as_ref().ok_or_else(context_error)?;
        let ctx = self.local.context()?;
        let b = &ctx["binding"];
        let device = self
            .store
            .read::<Value>("automatic-device.bin")?
            .ok_or_else(context_error)?;
        if b["package"] != p.manifest["package_id"]
            || b["capabilities"] != p.manifest["capabilities"]
            || b["ledger"] != p.profile["ledger_id"]
            || b["site"] != p.profile["site_id"]
            || b["pin"] != p.profile["tls"]["certificate_sha256"]
            || device["id"] != b["device"]
            || device["profile"] != self.store.profile()
        {
            return Err(context_error());
        }
        Ok(ctx)
    }
}
