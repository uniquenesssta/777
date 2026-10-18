use crate::{Connection, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use rustls::{
    client::{
        danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier},
        WebPkiServerVerifier,
    },
    pki_types::{CertificateDer, ServerName, UnixTime},
    DigitallySignedStruct, SignatureScheme,
};
use sha2::{Digest, Sha256};
use std::{sync::Arc, time::Duration};
#[derive(Debug)]
struct Pinned {
    inner: Arc<WebPkiServerVerifier>,
    pin: String,
}
impl ServerCertVerifier for Pinned {
    fn verify_server_cert(
        &self,
        end: &CertificateDer<'_>,
        chain: &[CertificateDer<'_>],
        name: &ServerName<'_>,
        ocsp: &[u8],
        now: UnixTime,
    ) -> std::result::Result<ServerCertVerified, rustls::Error> {
        if format!("{:x}", Sha256::digest(end.as_ref())) != self.pin {
            return Err(rustls::Error::General("CERTIFICATE_PIN_MISMATCH".into()));
        }
        // The retained service certificate is self-signed with CA=true. Ordinary
        // WebPKI leaf-chain validation rejects it as CaUsedAsEndEntity. Match the
        // accepted pinned transport: exact DER pin + validity + SAN + proof of key.
        let _ = (chain, ocsp);
        let (_, cert) = x509_parser::parse_x509_certificate(end.as_ref())
            .map_err(|_| rustls::Error::General("INVALID_SERVICE_CERTIFICATE".into()))?;
        let at = x509_parser::time::ASN1Time::from_timestamp(now.as_secs() as i64)
            .map_err(|_| rustls::Error::General("INVALID_CERTIFICATE_TIME".into()))?;
        if !cert.validity().is_valid_at(at) || cert.verify_signature(None).is_err() {
            return Err(rustls::Error::General("INVALID_SERVICE_CERTIFICATE".into()));
        }
        let parsed = rustls::server::ParsedCertificate::try_from(end)?;
        rustls::client::verify_server_name(&parsed, name)?;
        Ok(ServerCertVerified::assertion())
    }
    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        signature: &DigitallySignedStruct,
    ) -> std::result::Result<HandshakeSignatureValid, rustls::Error> {
        self.inner.verify_tls12_signature(message, cert, signature)
    }
    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        signature: &DigitallySignedStruct,
    ) -> std::result::Result<HandshakeSignatureValid, rustls::Error> {
        self.inner.verify_tls13_signature(message, cert, signature)
    }
    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.inner.supported_verify_schemes()
    }
}
pub fn configuration(c: &Connection) -> Result<rustls::ClientConfig> {
    let bad = || Error::new(422, "INVALID_CONNECTION");
    let u = reqwest::Url::parse(&c.url).map_err(|_| bad())?;
    if u.scheme() != "https"
        || u.host_str().is_none()
        || u.path() != "/"
        || u.query().is_some()
        || u.fragment().is_some()
        || !u.username().is_empty()
        || u.password().is_some()
        || c.url.len() > 4096
        || c.certificate_pem.len() > 65536
        || c.certificate_sha256.len() != 64
        || !c
            .certificate_sha256
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(bad());
    }
    let pem = c.certificate_pem.trim();
    let middle = pem
        .strip_prefix("-----BEGIN CERTIFICATE-----")
        .and_then(|p| p.strip_suffix("-----END CERTIFICATE-----"))
        .ok_or_else(bad)?;
    let der = STANDARD
        .decode(
            middle
                .chars()
                .filter(|c| !c.is_ascii_whitespace())
                .collect::<String>(),
        )
        .map_err(|_| bad())?;
    if format!("{:x}", Sha256::digest(&der)) != c.certificate_sha256 {
        return Err(Error::new(403, "CERTIFICATE_PIN_MISMATCH"));
    }
    let mut roots = rustls::RootCertStore::empty();
    roots.add(CertificateDer::from(der)).map_err(|_| bad())?;
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let inner = WebPkiServerVerifier::builder_with_provider(Arc::new(roots), provider.clone())
        .build()
        .map_err(|_| bad())?;
    let config = rustls::ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map_err(|_| bad())?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(Pinned {
            inner,
            pin: c.certificate_sha256.clone(),
        }))
        .with_no_client_auth();
    Ok(config)
}
pub fn build(c: &Connection) -> Result<reqwest::Client> {
    let bad = || Error::new(422, "INVALID_CONNECTION");
    reqwest::Client::builder()
        .use_preconfigured_tls(configuration(c)?)
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| bad())
}
#[cfg(test)]
mod tests {
    use super::*;
    fn verifier(host: &str, expired: bool, ca: bool) -> (Pinned, CertificateDer<'static>) {
        let mut params = rcgen::CertificateParams::new(vec![host.to_string()]).unwrap();
        if ca {
            params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Constrained(0));
        }
        if expired {
            params.not_before = rcgen::date_time_ymd(1970, 1, 1);
            params.not_after = rcgen::date_time_ymd(1971, 1, 1);
        }
        let key = rcgen::KeyPair::generate().unwrap();
        let cert = params.self_signed(&key).unwrap();
        let der = cert.der().clone();
        let mut roots = rustls::RootCertStore::empty();
        roots.add(der.clone()).unwrap();
        let inner = WebPkiServerVerifier::builder_with_provider(
            Arc::new(roots),
            Arc::new(rustls::crypto::ring::default_provider()),
        )
        .build()
        .unwrap();
        (
            Pinned {
                inner,
                pin: format!("{:x}", Sha256::digest(der.as_ref())),
            },
            der,
        )
    }
    #[test]
    fn pinned_legacy_ca_and_leaf_certificates_require_exact_identity_name_and_time() {
        let name = ServerName::try_from("localhost").unwrap();
        for ca in [true, false] {
            let (mut v, der) = verifier("localhost", false, ca);
            assert!(v
                .verify_server_cert(&der, &[], &name, &[], UnixTime::now())
                .is_ok());
            v.pin = "0".repeat(64);
            assert!(v
                .verify_server_cert(&der, &[], &name, &[], UnixTime::now())
                .is_err());
        }
        let (v, der) = verifier("wrong-host.example", false, true);
        assert!(v
            .verify_server_cert(&der, &[], &name, &[], UnixTime::now())
            .is_err());
        let (v, der) = verifier("localhost", true, true);
        assert!(v
            .verify_server_cert(&der, &[], &name, &[], UnixTime::now())
            .is_err());
    }
    #[test]
    fn invalid_destinations_and_bad_pin_never_build_a_client() {
        for url in [
            "http://localhost",
            "https://user@host",
            "https://host/api",
            "https://host/?q=1",
            "https://host/#x",
        ] {
            let c = Connection {
                url: url.into(),
                certificate_pem: String::new(),
                certificate_sha256: "0".repeat(64),
            };
            assert!(build(&c).is_err());
        }
    }
}
