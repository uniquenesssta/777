//! Dedicated owner-only upgrade material; never part of a public installer.
use super::*;
use serde::{Deserialize, Serialize};
use std::path::Path;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Kit {
    pub format: String,
    pub upgrade_id: String,
    pub issuer_id: String,
    pub issuer_hash: String,
    pub pair_hash: String,
    pub capabilities: Vec<String>,
    pub expires: i64,
    pub allowed_peer: String,
    pub certificate_pem: String,
    pub private_key_pem: String,
}
impl Kit {
    pub fn validate(&self) -> Result<()> {
        for id in [&self.upgrade_id, &self.issuer_id] {
            store::id(id)?;
        }
        permissions::validate("manager", &self.capabilities)?;
        if self.format != "777-host-automatic-upgrade-v1"
            || !crate::cluster::snapshot::hex(&self.issuer_hash)
            || !crate::cluster::snapshot::hex(&self.pair_hash)
            || self.allowed_peer.parse::<std::net::Ipv4Addr>().is_err()
            || self.expires <= auth::now()
            || self.expires > auth::now() + 86400
            || self.certificate_pem.len() > 65536
            || self.private_key_pem.len() > 65536
        {
            return fail(422, "UPGRADE_KIT_INVALID");
        }
        Ok(())
    }
}
pub fn prepare(
    out: &Path,
    state: &Path,
    peer: &str,
    notices: &Path,
    auxiliary: bool,
) -> Result<Value> {
    if out.exists() || state.exists() {
        return fail(409, "UPGRADE_REQUIRES_NEW_OUTPUT");
    }
    peer.parse::<std::net::Ipv4Addr>()
        .map_err(|_| Error::new(422, "UPGRADE_PEER_INVALID"))?;
    files::local(state, false)?;
    files::local(notices, true)?;
    let mut params =
        rcgen::CertificateParams::new(vec!["192.168.4.23".into()]).map_err(|_| denied())?;
    params.not_before = time::OffsetDateTime::now_utc() - time::Duration::minutes(5);
    params.not_after = time::OffsetDateTime::now_utc() + time::Duration::days(1);
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
    let key = rcgen::KeyPair::generate().map_err(|_| denied())?;
    let cert = params.self_signed(&key).map_err(|_| denied())?;
    let issuer_secret = secret()?;
    let pair_secret = secret()?;
    let kit = Kit {
        format: "777-host-automatic-upgrade-v1".into(),
        upgrade_id: store::uid()?,
        issuer_id: store::uid()?,
        issuer_hash: digest(&issuer_secret)?,
        pair_hash: digest(&pair_secret)?,
        capabilities: permissions::all(),
        expires: auth::now() + 86400,
        allowed_peer: peer.into(),
        certificate_pem: cert.pem(),
        private_key_pem: key.serialize_pem(),
    };
    let pending = json!({"format":"777-issuer-pending-v1","upgrade_id":kit.upgrade_id,"issuer_id":kit.issuer_id,"issuer_secret":issuer_secret,"pair_secret":pair_secret,"challenge":store::hash(auth::random::<32>()?),"temporary_connection":{"url":"https://192.168.4.23:8478","certificate_pem":cert.pem(),"certificate_sha256":store::hash(cert.der())},"profile":null});
    issuer_state::save(state, &pending, auxiliary)?;
    files::new_dir(out)?;
    files::protect(out, auxiliary)?;
    files::new_file(
        &out.join("execution.json"),
        &serde_json::to_vec(
            &json!({"format":"777-operation-context-v1","execution_id":quote_diagnostics::execution_id()}),
        )?,
    )?;
    files::new_file(&out.join("upgrade.json"), &serde_json::to_vec(&kit)?)?;
    files::copy(&std::env::current_exe()?, &out.join("quote-host.exe"))?;
    files::copy(notices, &out.join("THIRD_PARTY_NOTICES.md"))?;
    for(name,content)in [("upgrade.ps1",include_str!("../../../../deployment/windows/automatic/upgrade.ps1")),("cleanup.ps1",include_str!("../../../../deployment/windows/automatic/cleanup.ps1")),("host-identity.ps1",include_str!("../../../../deployment/windows/host-identity.ps1")),("host-elevation.ps1",include_str!("../../../../deployment/windows/portable/host-elevation.ps1")),("host-log.ps1",include_str!("../../../../deployment/windows/portable/host-log.ps1")),("upgrade.cmd","@echo off\r\ncd /d \"%~dp0\"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0upgrade.ps1\"\r\npause\r\n") ] {
        let mut raw=Vec::new();
        if name.ends_with(".ps1"){raw.extend_from_slice(&[0xef,0xbb,0xbf]);}
        raw.extend_from_slice(content.as_bytes());files::new_file(&out.join(name),&raw)?;
    }
    let mut manifest = serde_json::Map::new();
    for name in [
        "upgrade.json",
        "execution.json",
        "quote-host.exe",
        "THIRD_PARTY_NOTICES.md",
        "upgrade.ps1",
        "cleanup.ps1",
        "host-identity.ps1",
        "host-log.ps1",
        "host-elevation.ps1",
        "upgrade.cmd",
    ] {
        manifest.insert(name.into(), json!(files::sha(&out.join(name))?));
    }
    files::new_file(&out.join("files.json"), &serde_json::to_vec(&manifest)?)?;
    Ok(
        json!({"status":"owner_upgrade_prepared","upgrade_id":kit.upgrade_id,"expires":kit.expires,"contains_sensitive_upgrade_material":true}),
    )
}
