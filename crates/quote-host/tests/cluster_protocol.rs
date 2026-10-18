use quote_host::{
    cluster::{
        config::{self, Config, Role},
        membership,
        snapshot::{self, FileEntry, Manifest},
    },
    files,
};
use quote_ledger::store;
use serde_json::json;
use std::{collections::BTreeMap, fs, path::PathBuf};
struct Fixture {
    root: PathBuf,
    config: Config,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("777-cluster-test-{}", store::uid().unwrap()));
        fs::create_dir_all(root.join("private/cluster/generations")).unwrap();
        let inventory = store::create(&root.join("private/ledger.sqlite3")).unwrap();
        quote_host::auth::Auth::create(
            &root.join("private/auth.sqlite3"),
            "manager",
            "synthetic-cluster-password",
        )
        .unwrap();
        quote_host::outputs::Outputs::create(
            &root.join("private/outputs.sqlite3"),
            inventory["ledger_id"].as_str().unwrap(),
        )
        .unwrap();
        let cert = rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
        let config = Config {
            format: config::FORMAT.into(),
            cluster_id: store::uid().unwrap(),
            ledger_id: inventory["ledger_id"].as_str().unwrap().into(),
            node_id: store::uid().unwrap(),
            role: Role::Primary,
            primary: quote_security::Connection {
                url: "https://localhost:8477".into(),
                certificate_pem: cert.cert.pem(),
                certificate_sha256: store::hash(cert.cert.der()),
            },
        };
        files::new_file(
            &config::directory(&root).join("config.json"),
            &serde_json::to_vec(&config).unwrap(),
        )
        .unwrap();
        membership::create(&root).unwrap();
        Self { root, config }
    }
    fn snapshot(&self, generation: u64) -> (PathBuf, Manifest) {
        let stage = config::directory(&self.root).join(format!("stage-{}", store::uid().unwrap()));
        fs::create_dir(&stage).unwrap();
        let private = self.root.join("private");
        let inventory = quote_ledger::integrity::backup(
            &private.join("ledger.sqlite3"),
            &stage.join("ledger.sqlite3"),
        )
        .unwrap();
        files::snapshot(
            &private.join("auth.sqlite3"),
            &stage.join("auth.sqlite3"),
            quote_host::auth::APP,
            quote_host::auth::DDL,
        )
        .unwrap();
        quote_host::outputs::Outputs::open(private.join("outputs.sqlite3"), &self.config.ledger_id)
            .unwrap()
            .backup(&stage)
            .unwrap();
        let mut entries = BTreeMap::new();
        for name in ["ledger.sqlite3", "auth.sqlite3", "outputs.sqlite3"] {
            let path = stage.join(name);
            entries.insert(
                name.into(),
                FileEntry {
                    size: path.metadata().unwrap().len(),
                    sha256: files::sha(&path).unwrap(),
                },
            );
        }
        let manifest = Manifest {
            format: snapshot::FORMAT.into(),
            cluster_id: self.config.cluster_id.clone(),
            ledger_id: self.config.ledger_id.clone(),
            generation,
            inventory,
            files: entries,
        };
        (stage, manifest)
    }
    fn enroll(
        &self,
        invite: &serde_json::Value,
        node: &str,
        secret: &str,
    ) -> quote_host::Result<serde_json::Value> {
        membership::enroll(
            &self.root,
            &json!({"cluster_id":self.config.cluster_id,"ledger_id":self.config.ledger_id,"grant_id":invite["grant_id"],"ticket":invite["ticket"],"node_id":node,"credential":secret}),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
#[test]
fn tickets_bind_exactly_one_node_and_revocation_blocks_retry_and_forward_credentials() {
    let f = Fixture::new();
    let invite = membership::invite(&f.root).unwrap();
    let node = store::uid().unwrap();
    let secret = membership::credential().unwrap();
    let one = f.enroll(&invite, &node, &secret).unwrap();
    assert_eq!(one, f.enroll(&invite, &node, &secret).unwrap());
    assert_eq!(
        f.enroll(&invite, &store::uid().unwrap(), &secret)
            .unwrap_err()
            .code,
        "CLUSTER_INVITATION_ALREADY_USED"
    );
    assert!(f
        .enroll(&invite, &node, &membership::credential().unwrap())
        .is_err());
    membership::authenticate(&f.root, &node, &secret).unwrap();
    assert!(membership::authenticate(&f.root, &node, &membership::credential().unwrap()).is_err());
    membership::revoke(&f.root, &node).unwrap();
    assert_eq!(
        membership::authenticate(&f.root, &node, &secret)
            .unwrap_err()
            .code,
        "CLUSTER_PEER_REVOKED"
    );
    assert_eq!(
        f.enroll(&invite, &node, &secret).unwrap_err().code,
        "CLUSTER_PEER_REVOKED"
    );
    let records = membership::listing(&f.root).unwrap().to_string();
    assert!(!records.contains(&secret));
    assert!(!records.contains(invite["ticket"].as_str().unwrap()));
}
#[test]
fn manifest_paths_identity_hashes_and_monotonic_publication_are_enforced() {
    let f = Fixture::new();
    let (stage, mut m) = f.snapshot(2);
    snapshot::validate_manifest(&m, &f.config).unwrap();
    for bad in [
        "../service.json",
        "output-blobs/../../tls-key.pem",
        "tls-key.pem",
        "output-blobs/not-a-uuid.xlsx",
        "output-blobs/00000000-0000-0000-0000-000000000001.exe",
    ] {
        assert!(!snapshot::valid_name(bad));
    }
    let publication = snapshot::publish(&f.root, &stage, &m).unwrap();
    assert_eq!(snapshot::read(&f.root, &publication).unwrap().generation, 2);
    let (damaged, newer) = f.snapshot(3);
    fs::write(damaged.join("ledger.sqlite3"), b"corrupt chunk").unwrap();
    assert_eq!(
        snapshot::publish(&f.root, &damaged, &newer)
            .unwrap_err()
            .code,
        "CLUSTER_FILE_HASH_INVALID"
    );
    assert_eq!(
        snapshot::current(&f.root).unwrap().unwrap().sha256,
        publication.sha256
    );
    m.generation = 1;
    assert_eq!(
        snapshot::publish(&f.root, &stage, &m).unwrap_err().code,
        "CLUSTER_SOURCE_ROLLBACK"
    );
    m.generation = 2;
    m.files.get_mut("auth.sqlite3").unwrap().size = 2;
    assert_eq!(
        snapshot::publish(&f.root, &stage, &m).unwrap_err().code,
        "CLUSTER_GENERATION_CONFLICT"
    );
    m.ledger_id = store::uid().unwrap();
    assert!(snapshot::validate_manifest(&m, &f.config).is_err());
    let path = snapshot::folder(&f.root, &publication)
        .unwrap()
        .join("manifest.json");
    fs::write(path, b"corrupted").unwrap();
    assert_eq!(
        snapshot::read(&f.root, &publication).unwrap_err().code,
        "CLUSTER_MANIFEST_HASH_INVALID"
    );
}

#[test]
fn live_transfer_lease_retains_generation_until_acknowledged() {
    let f = Fixture::new();
    let invite = membership::invite(&f.root).unwrap();
    let node = store::uid().unwrap();
    f.enroll(&invite, &node, &membership::credential().unwrap())
        .unwrap();
    let (stage, first) = f.snapshot(1);
    let publication = snapshot::publish(&f.root, &stage, &first).unwrap();
    membership::lease(&f.root, &node, 1, &publication.sha256).unwrap();
    for generation in 2..=4 {
        let (stage, manifest) = f.snapshot(generation);
        snapshot::publish(&f.root, &stage, &manifest).unwrap();
    }
    snapshot::read(&f.root, &publication).unwrap();
    assert!(snapshot::chunk(&f.root, &publication, "../tls-key.pem", 0).is_err());
    assert!(snapshot::chunk(&f.root, &publication, "ledger.sqlite3", u64::MAX).is_err());
    membership::acknowledge(&f.root, &node, 1, &publication.sha256).unwrap();
    let (stage, manifest) = f.snapshot(5);
    snapshot::publish(&f.root, &stage, &manifest).unwrap();
    assert!(snapshot::read(&f.root, &publication).is_err());
    assert_eq!(
        fs::read_dir(snapshot::generations(&f.root))
            .unwrap()
            .count(),
        2
    );
}
