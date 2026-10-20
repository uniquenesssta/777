//! Public installation envelope. It carries registration scope, never issuer authority.
use crate::{Connection, Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
pub const PRIMARY: &str = "https://192.168.4.23:8477";
pub const ENROLLMENT: &str = "777-auto-enrollment-v1";
pub const AUTH: &str = "777-scoped-auth-v1";
pub const ISSUANCE: &str = "777-package-issuance-v1";
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Package {
    pub format: String,
    pub profile: Value,
    pub manifest: Value,
    pub secret: String,
}
pub fn protocols() -> Value {
    json!({"issuance":ISSUANCE,"enrollment":ENROLLMENT,"scoped_auth":AUTH,"cluster_snapshot":"777-cluster-snapshot-v2"})
}
fn invalid() -> Error {
    Error::new(403, "AUTOMATIC_PACKAGE_INVALID")
}
pub fn uuid(s: &str) -> bool {
    s.len() == 36
        && s.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
            }
        })
}
pub fn secret(s: &str) -> bool {
    s.len() == 43
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
pub fn connection(profile: &Value) -> Result<Connection> {
    let string = |v: &Value| v.as_str().map(str::to_owned).ok_or_else(invalid);
    if profile["format"] != "777-site-profile-v1"
        || profile["primary_url"] != PRIMARY
        || profile["required_protocols"] != protocols()
        || !["site_id", "ledger_id"]
            .iter()
            .all(|k| profile[k].as_str().is_some_and(uuid))
        || profile["trust_revision"].as_i64().is_none_or(|v| v < 1)
    {
        return Err(invalid());
    }
    let c = Connection {
        url: PRIMARY.into(),
        certificate_pem: string(&profile["tls"]["certificate_pem"])?,
        certificate_sha256: string(&profile["tls"]["certificate_sha256"])?,
    };
    crate::tls::configuration(&c)?;
    Ok(c)
}
impl Package {
    pub fn validate(&self, delivery: &str) -> Result<Connection> {
        if self.format == crate::local_package::FORMAT {
            return crate::local_package::validate(self, delivery);
        }
        let c = connection(&self.profile)?;
        let m = &self.manifest;
        if self.format != "777-automatic-package-v1"
            || !secret(&self.secret)
            || m["format"] != "777-package-manifest-v1"
            || m["delivery"] != delivery
            || !["manager", "sales"].contains(&delivery)
            || m["protocols"] != protocols()
            || m["site_id"] != self.profile["site_id"]
            || m["ledger_id"] != self.profile["ledger_id"]
            || m["trust_revision"] != self.profile["trust_revision"]
            || !["package_id", "issuer_id"]
                .iter()
                .all(|k| m[k].as_str().is_some_and(uuid))
            || m["artifact_sha256"].as_str().is_none_or(|s| {
                s.len() != 64
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
            || m["node_enrollment"] != (delivery == "manager")
        {
            return Err(invalid());
        }
        Ok(c)
    }
}
