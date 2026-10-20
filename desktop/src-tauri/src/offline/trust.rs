use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
#[derive(Clone, serde::Serialize, serde::Deserialize, PartialEq)]
pub(crate) struct Binding {
    pub(crate) site: String,
    pub(crate) ledger: String,
    pub(crate) device: String,
    pub(crate) package: String,
    pub(crate) subject: String,
    pub(crate) pin: String,
    pub(crate) role: String,
    pub(crate) capabilities: Vec<String>,
}
impl Local {
    pub(crate) fn prepare(&self, binding: &Binding, lease: &Value, catalog: &Value) -> Result<()> {
        let b = &lease["body"];
        let key = STANDARD
            .decode(lease["public_key"].as_str().unwrap_or(""))
            .map_err(|_| fault("OFFLINE_LEASE_INVALID"))?;
        let sig = STANDARD
            .decode(lease["signature"].as_str().unwrap_or(""))
            .map_err(|_| fault("OFFLINE_LEASE_INVALID"))?;
        let message = [b"777-offline-lease-v1\n".as_slice(), &canonical(b)?].concat();
        ring::signature::UnparsedPublicKey::new(&ring::signature::ED25519, key)
            .verify(&message, &sig)
            .map_err(|_| fault("OFFLINE_LEASE_INVALID"))?;
        let mut public_catalog = catalog.clone();
        crate::permissions::redact_financial(&mut public_catalog);
        public_catalog
            .as_object_mut()
            .ok_or_else(|| fault("OFFLINE_LEASE_INVALID"))?
            .remove("pricing_mode_version");
        if b["format"] != "777-offline-lease-v1"
            || b["site_id"] != binding.site
            || b["ledger_id"] != binding.ledger
            || b["device_id"] != binding.device
            || b["package_id"] != binding.package
            || b["subject"] != binding.subject
            || b["capabilities"] != json!(binding.capabilities)
            || b["price_version_id"] != catalog["price_version_id"]
            || b["price_sha256"] != quote_ledger::store::hash(canonical(&public_catalog)?)
            || b["rule_version"] != "business-v1"
            || b["numeric_profile"] != "numeric-v1"
        {
            return Err(fault("OFFLINE_BINDING_INVALID"));
        }
        identifier(&b["lease_id"])?;
        identifier(&b["stream_id"])?;
        let context = json!({"binding":binding,"lease":lease,"catalog":catalog,"profile":self.witness.parent().ok_or_else(||fault("LOCAL_IDENTITY_MISMATCH"))?.to_string_lossy()});
        self.transaction(|| {
            if let Some(old) = self.meta("context")? {
                for k in ["site", "ledger", "device", "subject", "pin", "role"] {
                    if old["binding"][k] != context["binding"][k] {
                        return Err(fault("LOCAL_IDENTITY_MISMATCH"));
                    }
                }
            }
            if let Some(old) = self.meta("context")? {
                if old["binding"]["capabilities"] != context["binding"]["capabilities"] {
                    self.narrow(&context)?;
                }
                if old["lease"]["body"]["epoch"] != b["epoch"]
                    || old["binding"]["package"] != context["binding"]["package"]
                {
                    self.put("feed_cursor", &Value::Null)?;
                    self.put("feed_pending", &Value::Null)?;
                    self.put("download", &Value::Null)?;
                }
            }
            self.put("context", &context)?;
            self.put("denied", &Value::Bool(false))?;
            self.put(
                &format!(
                    "price:{}",
                    catalog["price_version_id"].as_str().unwrap_or("")
                ),
                catalog,
            )?;
            self.check_clock(&context)?;
            Ok(())
        })
    }
    pub(crate) fn context(&self) -> Result<Value> {
        if self.meta("denied")? == Some(Value::Bool(true)) {
            return Err(DesktopError::new(403, "OFFLINE_AUTHORIZATION_CHANGED"));
        }
        let c = self
            .meta("context")?
            .ok_or_else(|| fault("OFFLINE_NOT_PREPARED"))?;
        if c["profile"]
            != self
                .witness
                .parent()
                .ok_or_else(|| fault("LOCAL_IDENTITY_MISMATCH"))?
                .to_string_lossy()
                .as_ref()
        {
            return Err(fault("LOCAL_IDENTITY_MISMATCH"));
        }
        Ok(c)
    }
    pub(super) fn writable(&self) -> Result<Value> {
        let c = self.context()?;
        self.check_clock(&c)?;
        Ok(c)
    }
    fn check_clock(&self, ctx: &Value) -> Result<()> {
        let current = now();
        let old = self
            .meta("clock")?
            .and_then(|v| v.as_i64())
            .unwrap_or(current)
            .max(self.witness_clock()?);
        if current + 300 < old
            || number(&ctx["lease"]["body"]["expires_at"])? < current
            || number(&ctx["lease"]["body"]["issued_at"])? > current + 300
        {
            return Err(fault("OFFLINE_AUTHORIZATION_EXPIRED"));
        }
        self.checkpoint(None, current.max(old))?;
        self.put("clock", &json!(current.max(old)))
    }
}
