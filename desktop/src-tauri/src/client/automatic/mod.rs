//! Automatic desktop protocol and request recovery orchestration.
#[cfg(all(test, any(feature = "manager", feature = "sales")))]
mod binding_tests;
mod identity;
mod package;
use super::*;
use quote_security::automatic::{Package, AUTH, ENROLLMENT};
use sha2::{Digest, Sha256};
fn invalid() -> DesktopError {
    DesktopError::new(403, "AUTOMATIC_IDENTITY_CONFLICT")
}
impl Desktop {
    pub(super) async fn bootstrap_automatic(&mut self) -> Result<Value> {
        let p = self.automatic_package.as_ref().ok_or_else(invalid)?.clone();
        let p = self.resolve_local_package(p).await?;
        let connection = p
            .validate(crate::startup::delivery())
            .map_err(|e| DesktopError::new(e.status, &e.code))?;
        let site = p.profile["site_id"].as_str().ok_or_else(invalid)?;
        let ledger = p.profile["ledger_id"].as_str().ok_or_else(invalid)?;
        let package = p.manifest["package_id"].as_str().ok_or_else(invalid)?;
        let mut device = identity::stage(
            &self.store,
            &p,
            &connection,
            crate::startup::delivery(),
            self.has_pending()?,
        )?;
        quote_diagnostics::event(
            "automatic.device.candidate",
            json!({"device_id":device.id,"package_id":package,"site_id":site,"ledger_id":ledger,"legacy":device.legacy}),
        );
        let connection = Connection {
            url: connection.url,
            certificate_pem: connection.certificate_pem,
            certificate_sha256: connection.certificate_sha256,
        };
        #[cfg(feature = "verification")]
        let connection = self.isolated_connection(connection)?;
        let mut s = Session {
            http: tls::build(&connection)?,
            connection,
            token: String::new(),
            subject: String::new(),
            role: String::new(),
        };
        let mut body = json!({"protocol":ENROLLMENT,"request_id":device.request_id,"package_id":package,"site_id":site,"ledger_id":ledger,"device_id":device.id});
        if device.legacy {
            s.token = device.secret.clone();
            transport::request_with_package(
                &s,
                "POST",
                "/v1/automatic/devices/adopt",
                Some(&body),
                Some(&p.secret),
            )
            .await?;
            device.legacy = false;
            device.package = package.into();
            self.store.replace("automatic-device.bin", &device)?;
        } else if device.package == package {
            s.token = p.secret.clone();
            body["device_secret_hash"] =
                json!(format!("{:x}", Sha256::digest(device.secret.as_bytes())));
            transport::request(&s, "POST", "/v1/automatic/devices/enroll", Some(&body)).await?;
        }
        s.token = device.secret.clone();
        let login_device = device.id.clone();
        let login = |id: &str| json!({"protocol":AUTH,"request_id":id,"device_id":login_device});
        let mut auth = transport::request(
            &s,
            "POST",
            "/v1/automatic/devices/session",
            Some(&login(&new_id()?)),
        )
        .await?;
        if device.package != package {
            s.token = auth["token"].as_str().ok_or_else(invalid)?.into();
            let upgrade =
                json!({"protocol":ENROLLMENT,"request_id":device.request_id,"package_id":package});
            transport::request_with_package(
                &s,
                "POST",
                "/v1/automatic/devices/upgrade",
                Some(&upgrade),
                Some(&p.secret),
            )
            .await?;
            device.package = package.into();
            device.request_id = new_id()?;
            self.store.replace("automatic-device.bin", &device)?;
            s.token = device.secret.clone();
            auth = transport::request(
                &s,
                "POST",
                "/v1/automatic/devices/session",
                Some(&login(&new_id()?)),
            )
            .await?;
        }
        let expected = if crate::startup::delivery() == "manager" {
            "admin"
        } else {
            "sales"
        };
        if auth["delivery"] != crate::startup::delivery()
            || auth["capabilities"] != p.manifest["capabilities"]
        {
            return Err(invalid());
        }
        s.token = auth["token"]
            .as_str()
            .filter(|v| v.starts_with("a2.") && v.len() == 46)
            .ok_or_else(invalid)?
            .into();
        s.subject = auth["subject"]
            .as_str()
            .filter(|s| quote_security::automatic::uuid(s))
            .ok_or_else(invalid)?
            .into();
        s.role = expected.into();
        if let Some(pending) = self.store.read::<Pending>("pending.bin")? {
            if pending.subject != s.subject
                || pending.url != s.connection.url
                || pending.pin != s.connection.certificate_sha256
            {
                return Err(invalid());
            }
        }
        let caps = transport::request(&s, "GET", "/v1/capabilities", None).await?;
        if caps["ledger_id"] != ledger || caps["cents_encoding"] != "decimal-string" {
            return Err(invalid());
        }
        self.auto_expires = auth["expires"].as_u64().ok_or_else(invalid)?;
        self.prepare_local(&s, &device.id, &p).await?;
        quote_diagnostics::event(
            "automatic.device.active",
            json!({"device_id":device.id,"package_id":package,"ledger_id":ledger,"subject":s.subject,"delivery":crate::startup::delivery()}),
        );
        self.session = Some(s);
        self.calculation = None;
        Ok(
            json!({"delivery":crate::startup::delivery(),"automatic":true,"session":{"subject":auth["subject"],"role":expected,"username":"","pending":self.has_pending()?,"ledger_id":ledger,"pricing_mode_version":caps["pricing_mode_version"]}}),
        )
    }
}
