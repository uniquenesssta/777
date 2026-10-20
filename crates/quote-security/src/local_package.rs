//! Offline developer signature and pinned, bounded first-contact resolution.
use crate::{
    automatic::{self, Package},
    Connection, Error, Result,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use ring::signature::{UnparsedPublicKey, ED25519};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
pub const FORMAT: &str = "777-local-package-v1";
pub const ENDPOINT: &str = "https://192.168.4.23:8479";
pub const PATH: &str = "/v1/automatic/packages/register";
fn invalid() -> Error {
    Error::new(403, "LOCAL_PACKAGE_INVALID")
}
pub fn signed_bytes(profile: &Value, manifest: &Value) -> Result<Vec<u8>> {
    let mut public = profile.clone();
    public
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("signature");
    serde_json::to_vec(&json!(["777-local-package-signature-v1", public, manifest]))
        .map_err(|_| invalid())
}
pub fn fingerprint(p: &Package) -> Result<String> {
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(p).map_err(|_| invalid())?)
    ))
}
pub fn validate(p: &Package, delivery: &str) -> Result<Connection> {
    let m = &p.manifest;
    if p.format != FORMAT
        || p.profile["format"] != "777-bootstrap-profile-v1"
        || p.profile["primary_url"] != ENDPOINT
        || !automatic::secret(&p.secret)
        || m["format"] != "777-local-manifest-v1"
        || m["delivery"] != delivery
        || !["manager", "sales"].contains(&delivery)
        || m["protocols"] != automatic::protocols()
        || m["node_enrollment"] != (delivery == "manager")
        || m["secret_hash"] != format!("{:x}", Sha256::digest(p.secret.as_bytes()))
        || !["package_id", "issuer_id"]
            .iter()
            .all(|k| m[k].as_str().is_some_and(automatic::uuid))
    {
        return Err(invalid());
    }
    let public = URL_SAFE_NO_PAD
        .decode(p.profile["public_key"].as_str().ok_or_else(invalid)?)
        .map_err(|_| invalid())?;
    let signature = URL_SAFE_NO_PAD
        .decode(p.profile["signature"].as_str().ok_or_else(invalid)?)
        .map_err(|_| invalid())?;
    if public.len() != 32 || signature.len() != 64 {
        return Err(invalid());
    }
    UnparsedPublicKey::new(&ED25519, public)
        .verify(&signed_bytes(&p.profile, m)?, &signature)
        .map_err(|_| invalid())?;
    let c = Connection {
        url: ENDPOINT.into(),
        certificate_pem: p.profile["tls"]["certificate_pem"]
            .as_str()
            .ok_or_else(invalid)?
            .into(),
        certificate_sha256: p.profile["tls"]["certificate_sha256"]
            .as_str()
            .ok_or_else(invalid)?
            .into(),
    };
    crate::tls::configuration(&c)?;
    Ok(c)
}
pub fn bound_manifest(p: &Package, profile: &Value) -> Result<Value> {
    automatic::connection(profile)?;
    let mut m = p.manifest.clone();
    m.as_object_mut().ok_or_else(invalid)?.remove("secret_hash");
    m["format"] = json!("777-package-manifest-v1");
    for k in ["site_id", "ledger_id", "trust_revision"] {
        m[k] = profile[k].clone();
    }
    Ok(m)
}
pub fn validate_binding(original: &Package, bound: &Package, delivery: &str) -> Result<()> {
    validate(original, delivery)?;
    bound.validate(delivery)?;
    if bound.manifest != bound_manifest(original, &bound.profile)?
        || bound.secret != original.secret
    {
        return Err(invalid());
    }
    Ok(())
}
pub async fn resolve(p: &Package, delivery: &str) -> Result<Package> {
    if p.format != FORMAT {
        p.validate(delivery)?;
        return Ok(p.clone());
    }
    let connection = validate(p, delivery)?;
    let client = crate::tls::build(&connection)?;
    let mut response = client
        .post(format!("{ENDPOINT}{PATH}"))
        .json(p)
        .send()
        .await
        .map_err(|_| Error::new(503, "AUTOMATIC_PRIMARY_UNAVAILABLE"))?;
    let status = response.status().as_u16();
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| invalid())? {
        if bytes.len() + chunk.len() > 131072 {
            return Err(invalid());
        }
        bytes.extend_from_slice(&chunk);
    }
    if status != 200 {
        return Err(Error::new(status, "AUTOMATIC_REGISTRATION_REJECTED"));
    }
    let bound: Package = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    validate_binding(p, &bound, delivery)?;
    Ok(bound)
}
