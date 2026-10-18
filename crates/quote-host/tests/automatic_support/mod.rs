use quote_host::{
    auth::Auth, automatic as a, files, outputs::Outputs, query::Queries, service::Service,
};
use quote_ledger::store;
use serde_json::{json, Value};
use std::path::PathBuf;
pub struct Fixture {
    pub root: PathBuf,
    pub service: Service,
    pub issuer: String,
    pub issuer_secret: String,
    pub issuer_token: String,
    pub kit: a::kit::Kit,
    pub pair_secret: String,
    pub ledger: String,
    pub legacy_token: String,
}
impl Fixture {
    pub fn new() -> Self {
        let root = std::env::temp_dir().join(format!("777-auto-{}", store::uid().unwrap()));
        std::fs::create_dir_all(root.join("private")).unwrap();
        let private = root.join("private");
        let inventory = store::create(&private.join("ledger.sqlite3")).unwrap();
        let ledger = inventory["ledger_id"].as_str().unwrap().to_owned();
        let mut auth = Auth::create(
            &private.join("auth.sqlite3"),
            "manager",
            "fixture-long-password",
        )
        .unwrap();
        let legacy_token = auth
            .login(
                &json!("manager"),
                &json!("fixture-long-password"),
                "fixture",
            )
            .unwrap()["token"]
            .as_str()
            .unwrap()
            .to_owned();
        a::schema::upgrade(&auth.path).unwrap();
        let key = rcgen::KeyPair::generate().unwrap();
        let cert = rcgen::CertificateParams::new(vec!["192.168.4.23".into()])
            .unwrap()
            .self_signed(&key)
            .unwrap();
        let connection = quote_security::Connection {
            url: a::trust::PRIMARY.into(),
            certificate_pem: cert.pem(),
            certificate_sha256: store::hash(cert.der()),
        };
        let issuer = store::uid().unwrap();
        let issuer_secret = a::secret().unwrap();
        let pair_secret = a::secret().unwrap();
        let kit = a::kit::Kit {
            format: "777-host-automatic-upgrade-v1".into(),
            upgrade_id: store::uid().unwrap(),
            issuer_id: issuer.clone(),
            issuer_hash: a::digest(&issuer_secret).unwrap(),
            pair_hash: a::digest(&pair_secret).unwrap(),
            capabilities: a::permissions::all(),
            expires: quote_host::auth::now() + 86400,
            allowed_peer: "192.0.2.80".into(),
            certificate_pem: cert.pem(),
            private_key_pem: key.serialize_pem(),
        };
        a::trust::install(&auth.connection().unwrap(), &ledger, &connection, &kit).unwrap();
        let issuer_token = a::sessions::issuer_session(
            &auth.connection().unwrap(),
            &envelope(a::ISSUANCE, json!({"issuer_id":issuer})),
            &issuer_secret,
        )
        .unwrap()["token"]
            .as_str()
            .unwrap()
            .to_owned();
        let outputs = Outputs::create(&private.join("outputs.sqlite3"), &ledger).unwrap();
        let service = Service {
            root: root.clone(),
            config: json!({"ledger_id":ledger}),
            ledger: private.join("ledger.sqlite3"),
            auth,
            devices: None,
            outputs: Some(outputs),
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: None,
        };
        for (name, raw) in [
            ("tls-cert.pem", cert.pem()),
            ("tls-key.pem", key.serialize_pem()),
            ("host-run.ps1", "fixture runner".into()),
            ("host-identity.ps1", "fixture owner".into()),
            ("rust-service-host.exe", "old host".into()),
            ("rust-host-notices.txt", "notices".into()),
        ] {
            files::new_file(&private.join(name), raw.as_bytes()).unwrap();
        }
        files::new_file(&root.join("service-cert.pem"), cert.pem().as_bytes()).unwrap();
        files::new_file(
            &root.join("client-template.json"),
            serde_json::to_string(
                &json!({"url":connection.url,"certificate_sha256":connection.certificate_sha256}),
            )
            .unwrap()
            .as_bytes(),
        )
        .unwrap();
        Self {
            root,
            service,
            issuer,
            issuer_secret,
            issuer_token,
            kit,
            pair_secret,
            ledger,
            legacy_token,
        }
    }
    pub fn c(&self) -> rusqlite::Connection {
        self.service.auth.connection().unwrap()
    }
    pub fn package(&self, delivery: &str, caps: &[&str], max: i64) -> (String, String, Value) {
        let mut caps = caps.to_vec();
        caps.sort();
        let id = store::uid().unwrap();
        let secret = a::secret().unwrap();
        let p = a::trust::profile(&self.c()).unwrap();
        let manifest = json!({"format":"777-package-manifest-v1","package_id":id,"issuer_id":self.issuer,"site_id":p["site_id"],"ledger_id":self.ledger,"trust_revision":1,"delivery":delivery,"capabilities":caps,"node_enrollment":delivery=="manager","release_version":"0.1.0","artifact_sha256":store::hash("fixture artifact"),"protocols":a::trust::protocols(),"enroll_before":quote_host::auth::now()+86400,"max_devices":max,"max_nodes":if delivery=="manager"{2}else{0}});
        let data = envelope(
            a::ISSUANCE,
            json!({"manifest":manifest,"secret_hash":a::digest(&secret).unwrap()}),
        );
        a::packages::create(&self.c(), &self.issuer, &data).unwrap();
        (id, secret, data)
    }
    pub fn candidate(&self, package: &str) -> (Value, String) {
        let secret = a::secret().unwrap();
        let p = a::trust::profile(&self.c()).unwrap();
        (
            envelope(
                a::ENROLLMENT,
                json!({"package_id":package,"site_id":p["site_id"],"ledger_id":self.ledger,"device_id":store::uid().unwrap(),"device_secret_hash":a::digest(&secret).unwrap()}),
            ),
            secret,
        )
    }
    pub fn activate(&self, data: &Value, package_secret: &str, device_secret: &str) -> Value {
        a::devices::enroll(&self.c(), data, package_secret).unwrap();
        a::devices::session(
            &self.c(),
            &envelope(a::SCOPED_AUTH, json!({"device_id":data["device_id"]})),
            device_secret,
        )
        .unwrap()
    }
    pub fn cluster(&self) {
        use quote_host::cluster::{
            config::{self, Config, Role},
            membership, snapshot,
        };
        let dir = config::directory(&self.root);
        std::fs::create_dir_all(snapshot::generations(&self.root)).unwrap();
        let c = Config {
            format: config::FORMAT.into(),
            cluster_id: store::uid().unwrap(),
            ledger_id: self.ledger.clone(),
            node_id: store::uid().unwrap(),
            role: Role::Primary,
            primary: config::connection(&self.root).unwrap(),
        };
        files::new_file(&dir.join("config.json"), &serde_json::to_vec(&c).unwrap()).unwrap();
        membership::create(&self.root).unwrap();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
pub fn envelope(protocol: &str, mut value: Value) -> Value {
    value["protocol"] = json!(protocol);
    value["request_id"] = json!(store::uid().unwrap());
    value
}
