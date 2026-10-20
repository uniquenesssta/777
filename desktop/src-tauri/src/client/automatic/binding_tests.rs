use super::*;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_security::local_package as local;
use ring::signature::{Ed25519KeyPair, KeyPair};
fn packages() -> (Package, Package) {
    let delivery = crate::startup::delivery();
    let key = rcgen::KeyPair::generate().unwrap();
    let cert = rcgen::CertificateParams::new(vec!["192.168.4.23".into()])
        .unwrap()
        .self_signed(&key)
        .unwrap();
    let pkcs8 = Ed25519KeyPair::generate_pkcs8(&ring::rand::SystemRandom::new()).unwrap();
    let signing = Ed25519KeyPair::from_pkcs8(pkcs8.as_ref()).unwrap();
    let tls = json!({"certificate_pem":cert.pem(),"certificate_sha256":format!("{:x}",Sha256::digest(cert.der()))});
    let mut profile = json!({"format":"777-bootstrap-profile-v1","primary_url":local::ENDPOINT,"public_key":URL_SAFE_NO_PAD.encode(signing.public_key().as_ref()),"tls":tls});
    let secret = "a".repeat(43);
    let manifest = json!({"format":"777-local-manifest-v1","package_id":new_id().unwrap(),"issuer_id":new_id().unwrap(),"delivery":delivery,"capabilities":["quote"],"node_enrollment":delivery=="manager","release_version":"1.2.3","artifact_sha256":"a".repeat(64),"protocols":quote_security::automatic::protocols(),"secret_hash":format!("{:x}",Sha256::digest(secret.as_bytes()))});
    profile["signature"] = json!(URL_SAFE_NO_PAD.encode(
        signing
            .sign(&local::signed_bytes(&profile, &manifest).unwrap())
            .as_ref()
    ));
    let original = Package {
        format: local::FORMAT.into(),
        profile,
        manifest,
        secret: secret.clone(),
    };
    let profile = json!({"format":"777-site-profile-v1","site_id":new_id().unwrap(),"ledger_id":new_id().unwrap(),"trust_revision":1,"primary_url":quote_security::automatic::PRIMARY,"required_protocols":quote_security::automatic::protocols(),"tls":tls});
    let bound = Package {
        format: "777-automatic-package-v1".into(),
        manifest: local::bound_manifest(&original, &profile).unwrap(),
        profile,
        secret,
    };
    (original, bound)
}
#[test]
fn restart_reads_protected_binding_without_network_or_replacing_device_and_pending_identity() {
    let path = std::env::temp_dir().join(format!("777-binding-{}", new_id().unwrap()));
    let (original, bound) = packages();
    let mut client = Desktop::new(path.clone(), !cfg!(windows)).unwrap();
    let connection = bound.validate(crate::startup::delivery()).unwrap();
    identity::stage(
        &client.store,
        &bound,
        &connection,
        crate::startup::delivery(),
        false,
    )
    .unwrap();
    client.store.replace("pending.bin",&json!({"path":"/v1/orders","body":{},"subject":new_id().unwrap(),"url":connection.url,"pin":connection.certificate_sha256})).unwrap();
    client
        .store
        .replace("automatic-package.bin", &original)
        .unwrap();
    client
        .store
        .replace(
            "automatic-binding.bin",
            &json!({"fingerprint":local::fingerprint(&original).unwrap(),"package":bound}),
        )
        .unwrap();
    let device = std::fs::read(path.join("automatic-device.bin")).unwrap();
    let pending = std::fs::read(path.join("pending.bin")).unwrap();
    client.load_background_package().unwrap();
    assert!(client.automatic_package.as_ref().unwrap().profile == bound.profile);
    drop(client);
    let mut restarted = Desktop::new(path.clone(), !cfg!(windows)).unwrap();
    restarted.load_background_package().unwrap();
    assert!(restarted.automatic_package.as_ref().unwrap().profile == bound.profile);
    assert!(device == std::fs::read(path.join("automatic-device.bin")).unwrap());
    assert!(pending == std::fs::read(path.join("pending.bin")).unwrap());
    // A valid original signature cannot authorize altered permissions in the cached response.
    let mut wrong = bound.clone();
    wrong.manifest["capabilities"] = json!(["quote", "orders"]);
    restarted
        .store
        .replace(
            "automatic-binding.bin",
            &json!({"fingerprint":local::fingerprint(&original).unwrap(),"package":wrong}),
        )
        .unwrap();
    assert!(restarted.load_background_package().is_err());
    drop(restarted);
    std::fs::remove_dir_all(path).unwrap();
}
