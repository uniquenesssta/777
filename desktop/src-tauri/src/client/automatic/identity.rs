//! Protected device candidates and legacy identity continuity.
use super::*;
use base64::Engine;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Device {
    pub(super) id: String,
    pub(super) secret: String,
    pub(super) site: String,
    pub(super) ledger: String,
    pub(super) package: String,
    pub(super) profile: String,
    pub(super) request_id: String,
    pub(super) legacy: bool,
}

pub(super) fn stage(
    store: &Store,
    p: &Package,
    connection: &quote_security::Connection,
    kind: &str,
    pending: bool,
) -> Result<Device> {
    let site = p.profile["site_id"].as_str().ok_or_else(invalid)?;
    let ledger = p.profile["ledger_id"].as_str().ok_or_else(invalid)?;
    let package = p.manifest["package_id"].as_str().ok_or_else(invalid)?;
    let device = match store.read::<Device>("automatic-device.bin")? {
        Some(d) => d,
        None => {
            let old = store.read::<crate::startup::Credential>("device.bin")?;
            let (id, secret, legacy) = if let Some(old) = old {
                if old.profile != store.profile()
                    || old.config.delivery != kind
                    || old.config.connection.url.trim_end_matches('/') != connection.url
                    || old.config.connection.certificate_sha256 != connection.certificate_sha256
                {
                    return Err(invalid());
                }
                (old.device_id, old.secret, true)
            } else {
                if pending {
                    return Err(invalid());
                }
                let mut raw = [0u8; 32];
                getrandom::getrandom(&mut raw).map_err(|_| invalid())?;
                (
                    new_id()?,
                    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(raw),
                    false,
                )
            };
            let d = Device {
                id,
                secret,
                site: site.into(),
                ledger: ledger.into(),
                package: package.into(),
                profile: store.profile(),
                request_id: new_id()?,
                legacy,
            };
            store.write("automatic-device.bin", &d)?;
            d
        }
    };
    if device.site != site
        || device.ledger != ledger
        || device.profile != store.profile()
        || !quote_security::automatic::uuid(&device.id)
        || !quote_security::automatic::secret(&device.secret)
    {
        return Err(invalid());
    }
    Ok(device)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (
        std::path::PathBuf,
        Store,
        Package,
        quote_security::Connection,
    ) {
        let path =
            std::env::temp_dir().join(format!("777-automatic-identity-{}", new_id().unwrap()));
        let store = Store::new(path.clone(), !cfg!(windows)).unwrap();
        let package = Package {
            format: "777-automatic-package-v1".into(),
            profile: json!({"site_id":new_id().unwrap(),"ledger_id":new_id().unwrap()}),
            manifest: json!({"package_id":new_id().unwrap()}),
            secret: "a".repeat(43),
        };
        let connection = quote_security::Connection {
            url: quote_security::automatic::PRIMARY.into(),
            certificate_pem: "fixture-not-used-by-staging".into(),
            certificate_sha256: "a".repeat(64),
        };
        (path, store, package, connection)
    }
    #[test]
    fn retries_reuse_the_candidate_and_a_second_profile_gets_an_independent_identity() {
        let (path, store, p, c) = fixture();
        let first = stage(&store, &p, &c, "sales", false).unwrap();
        let bytes = std::fs::read(path.join("automatic-device.bin")).unwrap();
        let again = stage(&store, &p, &c, "sales", false).unwrap();
        assert_eq!(first.id, again.id);
        assert_eq!(first.secret, again.secret);
        assert_eq!(first.request_id, again.request_id);
        assert_eq!(
            std::fs::read(path.join("automatic-device.bin")).unwrap(),
            bytes
        );
        let other_path = path.join("other");
        let other = Store::new(other_path, !cfg!(windows)).unwrap();
        let other = stage(&other, &p, &c, "sales", false).unwrap();
        assert_ne!(first.id, other.id);
        assert_ne!(first.secret, other.secret);
        std::fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn unknown_pending_or_site_change_cannot_create_a_new_identity_or_overwrite_the_original() {
        let (path, store, mut p, c) = fixture();
        assert!(stage(&store, &p, &c, "sales", true).is_err());
        assert!(!path.join("automatic-device.bin").exists());
        stage(&store, &p, &c, "sales", false).unwrap();
        let before = std::fs::read(path.join("automatic-device.bin")).unwrap();
        p.profile["ledger_id"] = json!(new_id().unwrap());
        assert!(stage(&store, &p, &c, "sales", false).is_err());
        assert_eq!(
            std::fs::read(path.join("automatic-device.bin")).unwrap(),
            before
        );
        std::fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn legacy_material_keeps_its_original_device_secret_and_profile() {
        let (path, store, p, c) = fixture();
        let id = new_id().unwrap();
        let credential = crate::startup::Credential {
            device_id: id.clone(),
            secret: "b".repeat(43),
            profile: store.profile(),
            config: crate::startup::Bootstrap {
                schema: "777-desktop-bootstrap-v1".into(),
                delivery: "sales".into(),
                connection: Connection {
                    url: c.url.clone(),
                    certificate_pem: c.certificate_pem.clone(),
                    certificate_sha256: c.certificate_sha256.clone(),
                },
                ticket: None,
                username: None,
                password: None,
            },
        };
        store.write("device.bin", &credential).unwrap();
        let before = std::fs::read(path.join("device.bin")).unwrap();
        let candidate = stage(&store, &p, &c, "sales", true).unwrap();
        assert_eq!(candidate.id, id);
        assert_eq!(candidate.secret, credential.secret);
        assert!(candidate.legacy);
        assert_eq!(std::fs::read(path.join("device.bin")).unwrap(), before);
        std::fs::remove_dir_all(path).unwrap();
    }
}
