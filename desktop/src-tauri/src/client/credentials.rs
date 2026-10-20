//! Development connection identities stay in the native protected profile.
use super::*;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Credential {
    url: String,
    pin: String,
    pub username: String,
    pub password: String,
    subject: String,
}
impl Desktop {
    fn credentials(&self) -> Result<Vec<Credential>> {
        Ok(self
            .store
            .read("development-identities.bin")?
            .unwrap_or_default())
    }
    pub(super) fn credential(&self, connection: &Connection) -> Result<Option<Credential>> {
        connections::development()?;
        Ok(self
            .credentials()?
            .into_iter()
            .find(|c| c.url == connection.url && c.pin == connection.certificate_sha256))
    }
    pub(super) fn remember_credential(
        &self,
        session: &Session,
        username: &str,
        password: &str,
    ) -> Result<()> {
        let mut credentials = self.credentials()?;
        credentials.retain(|c| c.url != session.connection.url);
        // Bound the protected record and retain the most recently used hosts.
        if credentials.len() >= 32 {
            credentials.remove(0);
        }
        credentials.push(Credential {
            url: session.connection.url.clone(),
            pin: session.connection.certificate_sha256.clone(),
            username: username.into(),
            password: password.into(),
            subject: session.subject.clone(),
        });
        self.store
            .replace("development-identities.bin", &credentials)
    }
    pub(super) async fn connect_selected(
        &mut self,
        connection: Connection,
        username: Option<String>,
        password: Option<String>,
    ) -> Result<Value> {
        connections::development()?;
        let (username, password) = match (username, password) {
            (Some(u), Some(p)) => (u, p),
            (None, None) => match self.credential(&connection)? {
                Some(c) => (c.username, c.password),
                None => default_identity()?,
            },
            _ => return Err(DesktopError::new(422, "INVALID_LOGIN")),
        };
        self.connect(connection, username, password, "host").await
    }
    pub(super) async fn renew_development(&mut self) -> Result<()> {
        connections::development()?;
        let old = self.session()?.clone();
        let c = self
            .credential(&old.connection)?
            .ok_or_else(|| DesktopError::new(401, "UNAUTHENTICATED"))?;
        let (session, _) = connections::login(old.connection, &c.username, &c.password).await?;
        if session.subject != old.subject
            || session.subject != c.subject
            || session.role != old.role
        {
            return Err(DesktopError::new(403, "PENDING_IDENTITY_MISMATCH"));
        }
        // Keep the calculation and original pending request ID across token renewal.
        self.session = Some(session);
        Ok(())
    }
}
#[cfg(not(any(feature = "manager", feature = "sales")))]
fn default_identity() -> Result<(String, String)> {
    // Owner-selected compatibility default for the already deployed Host.
    // This is a default, not a private credential; never ship it in formal deliveries.
    Ok(("manager".into(), "aaaaaaaaaaaa".into()))
}
#[cfg(any(feature = "manager", feature = "sales"))]
fn default_identity() -> Result<(String, String)> {
    Err(DesktopError::new(403, "MANUAL_LOGIN_DISABLED"))
}
