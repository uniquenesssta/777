use super::*;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PackageTarget {
    connection: Connection,
    ledger_id: String,
}
pub(super) fn development() -> Result<()> {
    if crate::startup::formal() {
        return Err(DesktopError::new(403, "MANUAL_LOGIN_DISABLED"));
    }
    Ok(())
}
fn formal_target(connection: &Connection) -> Result<()> {
    let url = reqwest::Url::parse(&connection.url)
        .map_err(|_| DesktopError::new(422, "INVALID_CONNECTION"))?;
    let host = url
        .host_str()
        .unwrap_or("")
        .trim_matches(['[', ']'])
        .trim_end_matches('.');
    let local = host.eq_ignore_ascii_case("localhost")
        || host.to_ascii_lowercase().ends_with(".localhost")
        || host.parse::<std::net::IpAddr>().is_ok_and(|ip| {
            ip.is_loopback()
                || ip.is_unspecified()
                || match ip {
                    std::net::IpAddr::V6(v) => v
                        .to_ipv4_mapped()
                        .is_some_and(|v| v.is_loopback() || v.is_unspecified()),
                    _ => false,
                }
        });
    if local {
        return Err(DesktopError::new(422, "PACKAGE_LOOPBACK_FORBIDDEN"));
    }
    Ok(())
}
pub(super) async fn identity(session: &Session) -> Result<String> {
    let caps = transport::request(session, "GET", "/v1/capabilities", None).await?;
    let ledger = if let Some(id) = caps["ledger_id"].as_str() {
        id.to_owned()
    } else {
        // Existing P08 primary hosts expose the ledger through this authenticated read.
        let peers = transport::request(session, "POST", "/v1/cluster/peers", Some(&json!({})))
            .await
            .map_err(|_| DesktopError::new(409, "HOST_IDENTITY_UNAVAILABLE"))?;
        peers["ledger_id"]
            .as_str()
            .ok_or_else(|| DesktopError::new(409, "HOST_IDENTITY_UNAVAILABLE"))?
            .to_owned()
    };
    identifier(&ledger)?;
    Ok(ledger)
}
async fn login(connection: Connection, username: &str, password: &str) -> Result<(Session, Value)> {
    if username.is_empty() || username.chars().count() > 64 || password.len() > 4096 {
        return Err(DesktopError::new(422, "INVALID_LOGIN"));
    }
    let mut session = Session {
        http: tls::build(&connection)?,
        connection,
        token: String::new(),
        subject: String::new(),
        role: String::new(),
    };
    let v = transport::request(
        &session,
        "POST",
        "/v1/login",
        Some(&json!({"username":username,"password":password})),
    )
    .await?;
    session.token = v["token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
        .into();
    session.subject = v["subject"]
        .as_str()
        .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
        .into();
    session.role = v["role"]
        .as_str()
        .filter(|s| ["admin", "sales"].contains(s))
        .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
        .into();
    let caps = transport::request(&session, "GET", "/v1/capabilities", None).await?;
    if caps["protocol"] != "777-service-v1" || caps["cents_encoding"] != "decimal-string" {
        return Err(DesktopError::new(409, "PROTOCOL_VERSION_CONFLICT"));
    }
    Ok((session, caps))
}
impl Desktop {
    pub(super) async fn connect(
        &mut self,
        connection: Connection,
        username: String,
        password: String,
    ) -> Result<Value> {
        development()?;
        if self.has_pending()? {
            let p = self.store.read::<Pending>("pending.bin")?.unwrap();
            if p.url != connection.url || p.pin != connection.certificate_sha256 {
                return Err(DesktopError::new(409, "PENDING_IDENTITY_MISMATCH"));
            }
        }
        let (session, caps) = login(connection.clone(), &username, &password).await?;
        let catalog = match transport::request(&session, "GET", "/v1/prices", None).await {
            Ok(value) => value,
            Err(e) if e.code == "PRICES_NOT_PUBLISHED" => Value::Null,
            Err(e) => return Err(e),
        };
        let settings = transport::request(&session, "GET", "/v1/settings", None).await?;
        let ledger_id = if session.role == "admin" {
            identity(&session).await.ok()
        } else {
            caps["ledger_id"].as_str().map(str::to_owned)
        };
        // Only a verified login replaces the persisted connection and active session.
        self.store.replace("connection.bin", &connection)?;
        let value = json!({"subject":session.subject,"role":session.role,"username":username,"pending":self.has_pending()?,"pricing_mode_version":caps["pricing_mode_version"],"catalog":catalog,"settings":settings,"ledger_id":ledger_id});
        self.store.replace("data-source-mode.bin", &"host")?;
        self.session = Some(session);
        self.calculation = None;
        Ok(value)
    }
    pub(super) fn package_target(&self) -> Result<Value> {
        development()?;
        self.admin()?;
        let target = self.store.read::<PackageTarget>("package-target.bin")?;
        Ok(json!({"target":target,"verified":self.package_session.is_some()}))
    }
    pub(super) async fn verify_package_target(
        &mut self,
        connection: Connection,
        username: String,
        password: String,
    ) -> Result<Value> {
        development()?;
        self.admin()?;
        formal_target(&connection)?;
        let (session, _) = login(connection.clone(), &username, &password).await?;
        if session.role != "admin" {
            return Err(DesktopError::new(403, "ADMIN_REQUIRED"));
        }
        let ledger_id = identity(&session).await?;
        let target = PackageTarget {
            connection,
            ledger_id,
        };
        self.store.replace("package-target.bin", &target)?;
        self.package_session = Some(session);
        self.package_target()
    }
    #[cfg(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    ))]
    pub(super) async fn verified_package_connection(&self) -> Result<Connection> {
        let target = self
            .store
            .read::<PackageTarget>("package-target.bin")?
            .ok_or_else(|| DesktopError::new(409, "PACKAGE_TARGET_REQUIRED"))?;
        formal_target(&target.connection)?;
        let session = self
            .package_session
            .as_ref()
            .ok_or_else(|| DesktopError::new(409, "PACKAGE_TARGET_REVERIFY"))?;
        if session.connection.url != target.connection.url
            || session.connection.certificate_sha256 != target.connection.certificate_sha256
            || identity(session).await? != target.ledger_id
        {
            return Err(DesktopError::new(409, "PACKAGE_TARGET_IDENTITY_MISMATCH"));
        }
        Ok(target.connection)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn package_blocks_all_loopback_spellings() {
        for host in [
            "localhost",
            "LOCALHOST.",
            "x.localhost",
            "127.0.0.1",
            "127.5.1.2",
            "[::1]",
            "[::ffff:127.0.0.1]",
            "0.0.0.0",
            "[::]",
        ] {
            let c = Connection {
                url: format!("https://{host}:8477"),
                certificate_pem: String::new(),
                certificate_sha256: String::new(),
            };
            assert!(formal_target(&c).is_err(), "{host}");
        }
    }
}
