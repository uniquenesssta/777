//! Developer-owned offline signer. The signing private key never leaves DPAPI state.
use super::*;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_security::{automatic::Package, local_package as local};
use ring::signature::{Ed25519KeyPair, KeyPair};
use std::path::Path;
fn key(s: &Value) -> Result<Ed25519KeyPair> {
    let raw = URL_SAFE_NO_PAD
        .decode(s["signing_key"].as_str().ok_or_else(denied)?)
        .map_err(|_| denied())?;
    Ed25519KeyPair::from_pkcs8(&raw).map_err(|_| denied())
}
pub fn ensure(path: &Path, auxiliary: bool) -> Result<Value> {
    if !path.exists() {
        files::local(path, false)?;
        let signing = Ed25519KeyPair::generate_pkcs8(&ring::rand::SystemRandom::new())
            .map_err(|_| denied())?;
        let mut params =
            rcgen::CertificateParams::new(vec!["192.168.4.23".into()]).map_err(|_| denied())?;
        params.not_before = time::OffsetDateTime::now_utc() - time::Duration::minutes(5);
        params.not_after = time::OffsetDateTime::now_utc() + time::Duration::days(3650);
        params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
        let tls_key = rcgen::KeyPair::generate().map_err(|_| denied())?;
        let cert = params.self_signed(&tls_key).map_err(|_| denied())?;
        let s = json!({"format":"777-local-issuer-v1","issuer_id":store::uid()?,"signing_key":URL_SAFE_NO_PAD.encode(signing.as_ref()),"certificate_pem":cert.pem(),"certificate_sha256":store::hash(cert.der()),"private_key_pem":tls_key.serialize_pem()});
        let raw = quote_security::protect::protect(&serde_json::to_vec(&s)?, true, auxiliary)
            .map_err(|e| Error::new(e.status, &e.code))?;
        // create_new avoids replacing an identity when concurrent first launches race.
        if let Err(e) = files::new_file(path, &raw) {
            if !path.exists() {
                return Err(e);
            }
        }
    }
    let s = issuer_state::load(path, auxiliary)?;
    if s["format"] != "777-local-issuer-v1" {
        return fail(409, "LOCAL_ISSUER_STATE_INVALID");
    }
    id(&s, "issuer_id")?;
    key(&s)?;
    Ok(s)
}
fn profile(s: &Value) -> Result<Value> {
    Ok(
        json!({"format":"777-bootstrap-profile-v1","primary_url":local::ENDPOINT,"public_key":URL_SAFE_NO_PAD.encode(key(s)?.public_key().as_ref()),"tls":{"certificate_pem":s["certificate_pem"],"certificate_sha256":s["certificate_sha256"]}}),
    )
}
pub fn status(path: &Path, auxiliary: bool) -> Result<Value> {
    let s = ensure(path, auxiliary)?;
    Ok(
        json!({"ready":true,"phase":"local_ready","issuer_id":s["issuer_id"],"profile":profile(&s)?}),
    )
}
pub fn provision(state: &Path, output: &Path, auxiliary: bool) -> Result<Value> {
    let s = ensure(state, auxiliary)?;
    let p = json!({"format":"777-local-host-trust-v1","issuer_id":s["issuer_id"],"profile":profile(&s)?,"private_key_pem":s["private_key_pem"]});
    files::new_file(output, &serde_json::to_vec(&p)?)?;
    Ok(json!({"status":"host_trust_exported","issuer_id":s["issuer_id"]}))
}
pub fn issue(
    state: &Path,
    input: &Path,
    candidate: &Path,
    output: &Path,
    auxiliary: bool,
) -> Result<Value> {
    let s = ensure(state, auxiliary)?;
    let input = files::read_json(input)?;
    crate::protocol::fields(
        &input,
        &[
            "package_id",
            "delivery",
            "permissions",
            "version",
            "artifact_sha256",
        ],
        &[],
    )?;
    let package_id = id(&input, "package_id")?;
    let delivery = input["delivery"].as_str().ok_or_else(denied)?;
    let permissions: Vec<String> = serde_json::from_value(input["permissions"].clone())?;
    permissions::validate(delivery, &permissions)?;
    hex(&input, "artifact_sha256")?;
    if input["version"]
        .as_str()
        .is_none_or(|s| s.is_empty() || s.len() > 64 || s.chars().any(char::is_control))
    {
        return fail(422, "PACKAGE_MANIFEST_INVALID");
    }
    let record = if candidate.exists() {
        let old = issuer_state::load(candidate, auxiliary)?;
        if old["input"] != input || old["issuer_id"] != s["issuer_id"] {
            return fail(409, "PACKAGE_ID_CONFLICT");
        }
        old
    } else {
        let secret = secret()?;
        let manifest = json!({"format":"777-local-manifest-v1","package_id":package_id,"issuer_id":s["issuer_id"],"delivery":delivery,"capabilities":permissions,"node_enrollment":delivery=="manager","release_version":input["version"],"artifact_sha256":input["artifact_sha256"],"protocols":trust::protocols(),"enroll_before":auth::now()+365*86400,"max_devices":1,"max_nodes":if delivery=="manager"{1}else{0},"secret_hash":digest(&secret)?});
        let mut profile = profile(&s)?;
        profile["signature"] = json!(URL_SAFE_NO_PAD.encode(
            key(&s)?
                .sign(&local::signed_bytes(&profile, &manifest).map_err(|_| denied())?)
                .as_ref()
        ));
        let p = Package {
            format: local::FORMAT.into(),
            profile,
            manifest,
            secret,
        };
        let record = json!({"input":input,"issuer_id":s["issuer_id"],"package":p});
        issuer_state::save(candidate, &record, auxiliary)?;
        record
    };
    let p: Package = serde_json::from_value(record["package"].clone())?;
    p.validate(delivery)
        .map_err(|e| Error::new(e.status, &e.code))?;
    files::replace_json(output, &record["package"])?;
    Ok(json!({"status":"signed_locally","package_id":package_id}))
}
