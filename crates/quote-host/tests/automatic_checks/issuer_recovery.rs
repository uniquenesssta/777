use crate::automatic_support::Fixture;
use quote_host::automatic as a;
use serde_json::json;

#[tokio::test]
async fn issuer_recovery_reports_the_failed_stage_without_replacing_protected_state() {
    let _ = rustls::crypto::ring::default_provider().install_default();
    let f = Fixture::new();
    for paired in [false, true] {
        // Owned local endpoint accepts TCP and closes during TLS; never contacts a LAN host.
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("https://{}", listener.local_addr().unwrap());
        let endpoint = tokio::spawn(async move {
            let (stream, _) =
                tokio::time::timeout(std::time::Duration::from_secs(10), listener.accept())
                    .await
                    .unwrap()
                    .unwrap();
            drop(stream);
        });
        let mut profile = a::trust::profile(&f.c()).unwrap();
        profile["primary_url"] = json!(url);
        let state = f.root.join(format!("issuer-{paired}.bin"));
        a::issuer_state::save(&state, &json!({
            "format":"777-issuer-pending-v1", "upgrade_id":f.kit.upgrade_id,
            "issuer_id":f.issuer, "issuer_secret":f.issuer_secret, "pair_secret":f.pair_secret,
            "challenge":"owned-test", "profile":if paired {profile.clone()} else {serde_json::Value::Null},
            "temporary_connection":{"url":url,"certificate_pem":profile["tls"]["certificate_pem"],"certificate_sha256":profile["tls"]["certificate_sha256"]}
        }), !cfg!(windows)).unwrap();
        let before = std::fs::read(&state).unwrap();
        let error = a::issuer_state::connect(&state, !cfg!(windows))
            .await
            .unwrap_err();
        assert_eq!(
            error.code,
            if paired {
                "ISSUER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED"
            } else {
                "ISSUER_PAIR_UNREACHABLE_OR_CERTIFICATE_REJECTED"
            }
        );
        assert_eq!(before, std::fs::read(&state).unwrap());
        assert_eq!(
            a::issuance::status(&state, !cfg!(windows)).unwrap()["phase"],
            "pending"
        );
        endpoint.await.unwrap();
    }
}
