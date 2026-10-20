use super::*;
impl Desktop {
    pub(in crate::client) async fn prepare_local(
        &mut self,
        s: &Session,
        device: &str,
        p: &quote_security::automatic::Package,
    ) -> Result<()> {
        // Old one-request pending operations must first be reconciled by original ID.
        if self.has_pending()? {
            return Ok(());
        }
        let ready = match transport::request(
            s,
            "POST",
            "/v1/offline/ready",
            Some(&json!({"protocol":FORMAT})),
        )
        .await
        {
            Ok(v) => v,
            Err(e) if [404, 426].contains(&e.status) => return Ok(()),
            Err(e) => return Err(e),
        };
        if ready["application"] != true || ready["local_orders"] != "777-local-orders-v1" {
            return Ok(());
        }
        let binding = crate::offline::Binding {
            site: p.profile["site_id"]
                .as_str()
                .ok_or_else(context_error)?
                .into(),
            ledger: p.profile["ledger_id"]
                .as_str()
                .ok_or_else(context_error)?
                .into(),
            device: device.into(),
            package: p.manifest["package_id"]
                .as_str()
                .ok_or_else(context_error)?
                .into(),
            subject: s.subject.clone(),
            pin: s.connection.certificate_sha256.clone(),
            role: s.role.clone(),
            capabilities: serde_json::from_value(p.manifest["capabilities"].clone())
                .map_err(|_| context_error())?,
        };
        if let Some(ctx) = self.local.meta("context")? {
            let b = &ctx["lease"]["body"];
            if ["site", "ledger", "device", "subject", "pin", "role"]
                .iter()
                .any(|k| ctx["binding"][*k] != json!(binding)[*k])
            {
                self.local.put("denied", &json!(true))?;
                return Err(context_error());
            }
            if b["epoch"] == ready["epoch"]
                && ctx["binding"] == json!(binding)
                && b["device_epoch"] == ready["device_epoch"]
                && b["user_epoch"] == ready["user_epoch"]
                && b["price_version_id"] == ready["price_version_id"]
                && b["expires_at"]
                    .as_str()
                    .and_then(|s| s.parse::<i64>().ok())
                    .is_some_and(|v| v > crate::offline::now() + 43200)
            {
                self.local.put("denied", &json!(false))?;
                self.local_settings(s, &binding.capabilities).await?;
                return Ok(());
            }
        }
        let id = match self.local.meta("lease_request")? {
            Some(Value::String(v)) => v,
            _ => {
                let id = new_id()?;
                self.local.put("lease_request", &json!(id))?;
                id
            }
        };
        let signed = transport::request(
            s,
            "POST",
            "/v1/offline/lease",
            Some(&json!({"protocol":FORMAT,"request_id":id})),
        )
        .await?;
        let catalog = transport::request(s, "GET", "/v1/prices", None).await?;
        self.local.prepare(&binding, &signed, &catalog)?;
        self.local.put("prices_changed", &json!(false))?;
        self.local.put("lease_request", &Value::Null)?;
        self.local_settings(s, &binding.capabilities).await?;
        Ok(())
    }
    async fn local_settings(&self, s: &Session, capabilities: &[String]) -> Result<()> {
        if capabilities.iter().any(|v| v == "settings") {
            let settings = transport::request(s, "GET", "/v1/settings", None).await?;
            self.local.put("settings", &settings)?;
        }
        Ok(())
    }
}
