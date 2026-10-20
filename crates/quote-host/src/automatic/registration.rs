//! Owner-provisioned public-key trust; registration never accepts a self-claimed role.
use super::*;
use quote_security::{automatic::Package, local_package as local};
use std::path::Path;
pub fn validate_provision(p: &Value) -> Result<()> {
    crate::protocol::fields(
        p,
        &["format", "issuer_id", "profile", "private_key_pem"],
        &[],
    )?;
    id(p, "issuer_id")?;
    let profile = &p["profile"];
    use base64::Engine;
    let public = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(profile["public_key"].as_str().ok_or_else(denied)?)
        .map_err(|_| denied())?;
    if p["format"] != "777-local-host-trust-v1"
        || profile["format"] != "777-bootstrap-profile-v1"
        || profile["primary_url"] != local::ENDPOINT
        || public.len() != 32
        || p["private_key_pem"]
            .as_str()
            .is_none_or(|s| s.is_empty() || s.len() > 65536)
    {
        return fail(422, "HOST_TRUST_INVALID");
    }
    let connection = issuer_state::connection(profile)?;
    quote_security::tls::configuration(&connection).map_err(|e| Error::new(e.status, &e.code))?;
    Ok(())
}
pub fn install(root: &Path, path: &Path, notices: &Path, auxiliary: bool) -> Result<Value> {
    let p = files::read_json(path)?;
    validate_provision(&p)?;
    let saved = root.join("private/automatic-bootstrap.bin");
    if saved.exists() && issuer_state::load(&saved, auxiliary)? != p {
        return fail(409, "HOST_TRUST_IDENTITY_CONFLICT");
    }
    if saved.exists() {
        let d = deployment::verify(root, auxiliary)?;
        let current = files::sha(&std::env::current_exe()?)?;
        let journal = files::read_json(&root.join("private/automatic-upgrade.json"))?;
        if journal["completed"] == true
            && d["host_sha256"] == current
            && files::sha(&root.join("private/rust-service-host.exe"))? == current
        {
            let _owner = files::Owner::acquire(root)?;
            let service = crate::service::Service::load(root, auxiliary, true)?;
            if service.config["bind"] != "192.168.4.23"
                || service.config["port"] != 8477
                || crate::cluster::config::required(root)?.role
                    != crate::cluster::config::Role::Primary
            {
                return fail(409, "AUTOMATIC_PRIMARY_ENDPOINT_CONFLICT");
            }
            trust::profile(&service.auth.connection()?)?;
            return Ok(
                json!({"status":"registration_already_configured","existing_data":"preserved"}),
            );
        }
    }
    let profile = &p["profile"];
    // Internal migration adapter preserves the existing ledger, 8477 certificate and accounts.
    // Its random pairing credential is never published and no pairing listener is installed.
    let kit = kit::Kit {
        format: "777-host-automatic-upgrade-v1".into(),
        upgrade_id: store::uid()?,
        issuer_id: id(&p, "issuer_id")?,
        issuer_hash: store::hash(format!("local-signature:{}", profile["public_key"])),
        pair_hash: digest(&secret()?)?,
        capabilities: permissions::all(),
        expires: auth::now() + 3600,
        allowed_peer: "127.0.0.1".into(),
        certificate_pem: profile["tls"]["certificate_pem"]
            .as_str()
            .ok_or_else(denied)?
            .into(),
        private_key_pem: p["private_key_pem"].as_str().ok_or_else(denied)?.into(),
    };
    upgrade::apply_material(root, &kit, notices, auxiliary, Some(&p))
}
pub fn register(c: &Connection, provision: &Value, p: &Package) -> Result<Package> {
    validate_provision(provision)?;
    let delivery = p.manifest["delivery"].as_str().ok_or_else(denied)?;
    p.validate(delivery)
        .map_err(|e| Error::new(e.status, &e.code))?;
    let mut public = p.profile.clone();
    public
        .as_object_mut()
        .ok_or_else(denied)?
        .remove("signature");
    if p.format != local::FORMAT
        || p.manifest["issuer_id"] != provision["issuer_id"]
        || public != provision["profile"]
    {
        return Err(denied());
    }
    let profile = trust::profile(c)?;
    let manifest = local::bound_manifest(p, &profile).map_err(|e| Error::new(e.status, &e.code))?;
    let issuer = id(&p.manifest, "issuer_id")?;
    let package_id = id(&p.manifest, "package_id")?;
    let result = packages::create(
        c,
        &issuer,
        &json!({"protocol":ISSUANCE,"request_id":package_id,"manifest":manifest,"secret_hash":digest(&p.secret)?}),
    )?;
    if result["status"] != "active" {
        return Err(denied());
    }
    Ok(Package {
        format: "777-automatic-package-v1".into(),
        profile,
        manifest,
        secret: p.secret.clone(),
    })
}
