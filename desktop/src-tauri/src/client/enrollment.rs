//! Enrollment candidates are kept separately until the server confirms the identity.
use super::*;
use crate::startup::{self, Bootstrap, Credential};
fn candidate(store: &Store, config: Bootstrap) -> Result<Credential> {
    use base64::Engine;
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).map_err(|_| DesktopError::new(503, "RANDOM_UNAVAILABLE"))?;
    Ok(Credential {
        config,
        device_id: new_id()?,
        secret: base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes),
        profile: store.profile(),
    })
}
fn same(a: &Bootstrap, b: &Bootstrap) -> bool {
    serde_json::to_value(a).ok() == serde_json::to_value(b).ok()
}
impl Desktop {
    fn stage_enrollment(&self, config: Bootstrap) -> Result<()> {
        config.validate(startup::delivery())?;
        if let Some(pending) = self.store.read::<Pending>("pending.bin")? {
            if pending.url != config.connection.url
                || pending.pin != config.connection.certificate_sha256
            {
                return Err(DesktopError::new(409, "PENDING_IDENTITY_MISMATCH"));
            }
        }
        if let Some(old) = self.store.read::<Credential>("device-candidate.bin")? {
            if same(&old.config, &config) {
                return Ok(());
            }
        }
        if let Some(old) = self.store.read::<Credential>("device.bin")? {
            if same(&old.config, &config) {
                self.store.clear("device-candidate.bin")?;
                return Ok(());
            }
        }
        self.store
            .replace("device-candidate.bin", &candidate(&self.store, config)?)
    }
    pub(super) async fn import_enrollment(&mut self, path: &str) -> Result<Value> {
        if !startup::formal() {
            return Err(DesktopError::new(403, "DELIVERY_ROLE_MISMATCH"));
        }
        let config = crate::connection_file::read::<Bootstrap>(path, "777-desktop-bootstrap-v1")?;
        self.stage_enrollment(config)?;
        self.store.clear("bootstrap.json")?;
        // Return no file contents or ticket. The frontend calls bootstrap to enter the workbench.
        self.bootstrap_formal().await?;
        Ok(json!({"registered":true}))
    }
    pub(super) async fn bootstrap_formal(&mut self) -> Result<Value> {
        if self.automatic_package.is_some() {
            if self.local.active()? {
                return self.local_bootstrap();
            }
            self.automatic_retry.ready()?;
            let result = self.bootstrap_automatic().await;
            self.automatic_retry.record(&result);
            return result;
        }
        #[cfg(quote777_packaged)]
        if crate::startup::package_info()["device_protocol"] == "777-auto-enrollment-v1" {
            return Err(DesktopError::new(409, "AUTOMATIC_PACKAGE_UNAVAILABLE"));
        }
        let kind = startup::delivery();
        if self
            .store
            .read::<Credential>("device-candidate.bin")?
            .is_none()
        {
            if let Some(config) = self.store.bootstrap::<Bootstrap>()? {
                self.stage_enrollment(config)?;
            }
        }
        let staged = self.store.read::<Credential>("device-candidate.bin")?;
        let is_candidate = staged.is_some();
        let credential = staged
            .or(self.store.read::<Credential>("device.bin")?)
            .ok_or_else(|| DesktopError::new(409, "DEPLOYMENT_NOT_CONFIGURED"))?;
        credential.config.validate(kind)?;
        if credential.profile != self.store.profile() {
            return Err(DesktopError::new(403, "DEVICE_PROFILE_MISMATCH"));
        }
        let mut session = Session {
            http: tls::build(&credential.config.connection)?,
            connection: credential.config.connection.clone(),
            token: String::new(),
            subject: String::new(),
            role: String::new(),
        };
        let enrolled=transport::request(&session,"POST","/v1/device/enroll",Some(&json!({"ticket":credential.config.ticket,"device_id":credential.device_id,"device_secret":credential.secret,"delivery":kind}))).await?;
        if enrolled["protocol"] != "777-device-auth-v1" {
            return Err(DesktopError::new(409, "DEVICE_PROTOCOL_CONFLICT"));
        }
        let v=transport::request(&session,"POST","/v1/device/session",Some(&json!({"device_id":credential.device_id,"device_secret":credential.secret,"delivery":kind}))).await?;
        let expected = if kind == "manager" { "admin" } else { "sales" };
        if v["protocol"] != "777-device-auth-v1"
            || v["role"] != expected
            || v["subject"] != enrolled["subject"]
        {
            return Err(DesktopError::new(403, "DELIVERY_ROLE_MISMATCH"));
        }
        session.token = v["token"]
            .as_str()
            .filter(|s| s.len() == 43)
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
            .into();
        session.subject = v["subject"]
            .as_str()
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
            .into();
        session.role = expected.into();
        if let Some(pending) = self.store.read::<Pending>("pending.bin")? {
            if pending.subject != session.subject
                || pending.url != session.connection.url
                || pending.pin != session.connection.certificate_sha256
            {
                return Err(DesktopError::new(409, "PENDING_IDENTITY_MISMATCH"));
            }
        }
        let expires = v["expires"]
            .as_u64()
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?;
        let caps = transport::request(&session, "GET", "/v1/capabilities", None).await?;
        if caps["device_auth"] != "777-device-auth-v1" || caps["cents_encoding"] != "decimal-string"
        {
            return Err(DesktopError::new(409, "DEVICE_PROTOCOL_CONFLICT"));
        }
        if is_candidate {
            self.store.replace("device.bin", &credential)?;
            self.store.clear("device-candidate.bin")?;
        }
        self.store.clear("bootstrap.json")?;
        self.session = Some(session);
        self.calculation = None;
        self.auto_expires = expires;
        Ok(
            json!({"delivery":kind,"automatic":true,"session":{"subject":v["subject"],"role":expected,"username":v["username"],"pending":self.has_pending()?,"pricing_mode_version":caps["pricing_mode_version"]}}),
        )
    }
}
