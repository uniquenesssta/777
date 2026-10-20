//! Durable mutation journal: validate before staging and preserve unknown results.
use super::*;
#[cfg(test)]
mod tests;
impl Desktop {
    pub(super) async fn mutate(&mut self, path: &str, mut body: Value) -> Result<Value> {
        if self.store.read::<Pending>("pending.bin")?.is_some() {
            return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
        }
        if self.session()?.token.is_empty() {
            if crate::startup::formal() {
                return Err(DesktopError::new(401, "UNAUTHENTICATED"));
            }
            self.renew_development().await?;
        }
        let s = self.session()?;
        body["request_id"] = json!(new_id()?);
        if serde_json::to_vec(&body)
            .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?
            .len()
            > REQUEST_LIMIT
        {
            return Err(DesktopError::new(413, "BODY_TOO_LARGE"));
        }
        let p = Pending {
            path: path.into(),
            body,
            subject: s.subject.clone(),
            url: s.connection.url.clone(),
            pin: s.connection.certificate_sha256.clone(),
        };
        self.validate_pending(&p).await?;
        self.store.write("pending.bin", &p)?;
        self.send_pending(&p).await
    }
    async fn send_pending(&mut self, p: &Pending) -> Result<Value> {
        self.validate_pending(p).await?;
        match self.request("POST", &p.path, Some(&p.body)).await {
            Ok(v) => {
                self.store.clear("pending.bin")?;
                Ok(v)
            }
            Err(e) if e.status == 0 || e.status >= 500 || e.status == 202 || e.status == 401 => {
                Err(DesktopError::new(202, "COMMIT_UNKNOWN"))
            }
            Err(e) => {
                self.store.clear("pending.bin")?;
                Err(e)
            }
        }
    }
    async fn validate_pending(&mut self, p: &Pending) -> Result<()> {
        let s = self.session()?;
        if p.subject != s.subject
            || p.url != s.connection.url
            || p.pin != s.connection.certificate_sha256
        {
            return Err(DesktopError::new(403, "PENDING_IDENTITY_MISMATCH"));
        }
        permissions::pending(&permissions::selected()?, &p.path, &p.body)?;
        if let Some(id) = permissions::output_mutation_job(&p.path) {
            self.authorize_output(id).await?;
        }
        Ok(())
    }
    pub(super) async fn recover_pending(&mut self, retry: bool) -> Result<Value> {
        let Some(p) = self.store.read::<Pending>("pending.bin")? else {
            return Ok(json!({"pending":false,"result":null}));
        };
        let s = self.session()?;
        if p.subject != s.subject
            || p.url != s.connection.url
            || p.pin != s.connection.certificate_sha256
        {
            return Err(DesktopError::new(403, "PENDING_IDENTITY_MISMATCH"));
        }
        self.validate_pending(&p).await?;
        let receipt = self
            .request(
                "GET",
                &format!(
                    "/v1/requests/{}",
                    identifier(p.body["request_id"].as_str().unwrap_or(""))?
                ),
                None,
            )
            .await?;
        if !receipt["result"].is_null() {
            self.store.clear("pending.bin")?;
            return Ok(
                json!({"pending":false,"result":receipt["result"],"path":p.path,"submitted":if ["/v1/orders","/v1/order-save"].contains(&p.path.as_str()) {p.body.clone()} else {Value::Null}}),
            );
        }
        if retry {
            return Ok(
                json!({"pending":false,"result":self.send_pending(&p).await?,"path":p.path,"submitted":if ["/v1/orders","/v1/order-save"].contains(&p.path.as_str()) {p.body.clone()} else {Value::Null}}),
            );
        }
        Ok(json!({"pending":true,"result":null,"request_id":p.body["request_id"]}))
    }
}
