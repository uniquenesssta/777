use super::*;
use crate::automatic_fixture as support;
use quote_security::automatic::Package;
#[tokio::test]
async fn pinned_https_registration_rejects_tampering_and_preserves_business_identity() {
    let f = support::Fixture::new();
    let state = f.root.join("signer.bin");
    let auxiliary = !cfg!(windows);
    local_issuer::ensure(&state, auxiliary).unwrap();
    // Only this test certificate adds loopback SAN; production endpoint stays fixed.
    let mut signing = issuer_state::load(&state, auxiliary).unwrap();
    let key = rcgen::KeyPair::generate().unwrap();
    let cert = rcgen::CertificateParams::new(vec!["192.168.4.23".into(), "127.0.0.1".into()])
        .unwrap()
        .self_signed(&key)
        .unwrap();
    signing["certificate_pem"] = json!(cert.pem());
    signing["certificate_sha256"] = json!(store::hash(cert.der()));
    signing["private_key_pem"] = json!(key.serialize_pem());
    issuer_state::save(&state, &signing, auxiliary).unwrap();
    let provision_path = f.root.join("provision.json");
    local_issuer::provision(&state, &provision_path, auxiliary).unwrap();
    let provision = files::read_json(&provision_path).unwrap();
    let mut kit: kit::Kit = serde_json::from_value(serde_json::to_value(&f.kit).unwrap()).unwrap();
    kit.issuer_id = provision["issuer_id"].as_str().unwrap().into();
    kit.upgrade_id = store::uid().unwrap();
    kit.issuer_hash = store::hash(format!(
        "local-signature:{}",
        provision["profile"]["public_key"]
    ));
    let profile = trust::profile(&f.c()).unwrap();
    trust::install(
        &f.c(),
        &f.ledger,
        &issuer_state::connection(&profile).unwrap(),
        &kit,
    )
    .unwrap();
    let input = f.root.join("input.json");
    let candidate = f.root.join("candidate.bin");
    let output = f.root.join("package.json");
    files::replace_json(&input,&json!({"package_id":store::uid().unwrap(),"delivery":"sales","permissions":["quote"],"version":"1.2.3","artifact_sha256":store::hash("payload")})).unwrap();
    local_issuer::issue(&state, &input, &candidate, &output, auxiliary).unwrap();
    let p: Package = serde_json::from_value(files::read_json(&output).unwrap()).unwrap();
    let service = Service {
        root: f.root.clone(),
        config: f.service.config.clone(),
        ledger: f.service.ledger.clone(),
        auth: crate::auth::Auth::open(f.service.auth.path.clone()).unwrap(),
        devices: None,
        outputs: None,
        queries: crate::query::Queries::new().unwrap(),
        auxiliary,
        font: None,
        test_fault: None,
    };
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("https://{}", listener.local_addr().unwrap());
    let stop = Arc::new(AtomicBool::new(false));
    let dirty = Arc::new(AtomicBool::new(false));
    let server = listen(
        Arc::new(Mutex::new(service)),
        stop.clone(),
        dirty.clone(),
        provision,
        listener,
    )
    .await
    .unwrap();
    let mut connection = p.validate("sales").unwrap();
    connection.url = url.clone();
    let client = quote_security::tls::build(&connection).unwrap();
    let endpoint = format!("{url}{}", quote_security::local_package::PATH);
    let response = client.post(&endpoint).json(&p).send().await.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.headers()["cache-control"], "no-store");
    let bound: Package = response.json().await.unwrap();
    quote_security::local_package::validate_binding(&p, &bound, "sales").unwrap();
    assert!(bound.profile == profile);
    assert!(dirty.load(Ordering::SeqCst));
    let mut changed = p.clone();
    changed.manifest["delivery"] = json!("manager");
    assert_eq!(
        client
            .post(&endpoint)
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        client
            .post(&endpoint)
            .header("origin", "https://example.invalid")
            .json(&p)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(
        client
            .get(format!("{url}/v1/orders"))
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    // A different valid certificate is rejected even when its SAN names the same endpoint.
    let other = rcgen::CertificateParams::new(vec!["127.0.0.1".into()])
        .unwrap()
        .self_signed(&rcgen::KeyPair::generate().unwrap())
        .unwrap();
    connection.certificate_pem = other.pem();
    connection.certificate_sha256 = store::hash(other.der());
    assert!(quote_security::tls::build(&connection)
        .unwrap()
        .post(&endpoint)
        .json(&p)
        .send()
        .await
        .is_err());
    stop.store(true, Ordering::SeqCst);
    server.await.unwrap();
}
