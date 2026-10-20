use crate::automatic_support::{envelope, Fixture};
use quote_host::{automatic as a, files};
use quote_ledger::store;
use quote_security::{automatic::Package, local_package as local};
use serde_json::{json, Value};
use std::path::PathBuf;
struct Signer {
    root: PathBuf,
    state: PathBuf,
    auxiliary: bool,
}
impl Signer {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("777-local-{}", store::uid().unwrap()));
        std::fs::create_dir(&root).unwrap();
        let state = root.join("signer.bin");
        let auxiliary = !cfg!(windows);
        a::local_issuer::status(&state, auxiliary).unwrap();
        Self {
            root,
            state,
            auxiliary,
        }
    }
    fn provision(&self) -> Value {
        let path = self.root.join(format!("{}.json", store::uid().unwrap()));
        a::local_issuer::provision(&self.state, &path, self.auxiliary).unwrap();
        files::read_json(&path).unwrap()
    }
    fn package(&self, delivery: &str) -> (Package, PathBuf, PathBuf, PathBuf) {
        let id = store::uid().unwrap();
        let input = self.root.join(format!("{id}.input"));
        let candidate = self.root.join(format!("{id}.bin"));
        let output = self.root.join(format!("{id}.package"));
        files::replace_json(&input,&json!({"package_id":id,"delivery":delivery,"permissions":["quote"],"version":"1.2.3","artifact_sha256":store::hash("real payload identity")})).unwrap();
        a::local_issuer::issue(&self.state, &input, &candidate, &output, self.auxiliary).unwrap();
        (
            serde_json::from_value(files::read_json(&output).unwrap()).unwrap(),
            input,
            candidate,
            output,
        )
    }
    fn install_trust(&self, f: &Fixture, p: &Value) {
        let mut kit =
            serde_json::from_value::<a::kit::Kit>(serde_json::to_value(&f.kit).unwrap()).unwrap();
        kit.upgrade_id = store::uid().unwrap();
        kit.issuer_id = p["issuer_id"].as_str().unwrap().into();
        kit.issuer_hash = store::hash(format!("local-signature:{}", p["profile"]["public_key"]));
        let profile = a::trust::profile(&f.c()).unwrap();
        let connection = a::issuer_state::connection(&profile).unwrap();
        a::trust::install(&f.c(), &f.ledger, &connection, &kit).unwrap();
    }
}
impl Drop for Signer {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
#[test]
fn local_signing_needs_no_host_and_retry_reuses_exact_identity_without_exporting_private_key() {
    let s = Signer::new();
    let before = std::fs::read(&s.state).unwrap();
    let (p, input, candidate, output) = s.package("sales");
    assert!(p.validate("sales").is_ok());
    assert!(p.profile["site_id"].is_null() && p.profile["ledger_id"].is_null());
    let first = std::fs::read(&output).unwrap();
    a::local_issuer::issue(&s.state, &input, &candidate, &output, s.auxiliary).unwrap();
    assert!(first == std::fs::read(&output).unwrap());
    assert!(before == std::fs::read(&s.state).unwrap());
    let protected = a::issuer_state::load(&s.state, s.auxiliary).unwrap();
    let provision = s.provision();
    let public = String::from_utf8(first).unwrap();
    for secret in [
        protected["signing_key"].as_str().unwrap(),
        protected["private_key_pem"].as_str().unwrap(),
    ] {
        assert!(!public.contains(secret));
    }
    assert!(!store::encoded(&provision).contains(protected["signing_key"].as_str().unwrap()));
    assert!(a::local_issuer::status(&s.state, s.auxiliary).unwrap()["ready"] == true);
}
#[test]
fn signed_roles_permissions_and_secrets_cannot_be_changed_or_self_authorized() {
    let s = Signer::new();
    let f = Fixture::new();
    let provision = s.provision();
    s.install_trust(&f, &provision);
    let (p, _, _, _) = s.package("sales");
    for (key, value) in [
        ("delivery", json!("manager")),
        ("capabilities", json!(["quote", "finance"])),
        ("max_devices", json!(4096)),
        ("artifact_sha256", json!(store::hash("changed"))),
    ] {
        let mut changed = p.clone();
        changed.manifest[key] = value;
        assert!(a::registration::register(&f.c(), &provision, &changed).is_err());
    }
    let mut changed = p.clone();
    changed.secret = a::secret().unwrap();
    assert!(changed.validate("sales").is_err());
    let outsider = Signer::new();
    let (other, _, _, _) = outsider.package("manager");
    assert!(other.validate("manager").is_ok());
    assert!(a::registration::register(&f.c(), &provision, &other).is_err());
    assert_eq!(
        f.c()
            .query_row("SELECT count(*) FROM package_grants", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn first_contact_binds_existing_ledger_and_enforces_device_role_and_revocation() {
    for delivery in ["manager", "sales"] {
        let s = Signer::new();
        let f = Fixture::new();
        let provision = s.provision();
        s.install_trust(&f, &provision);
        let profile = a::trust::profile(&f.c()).unwrap();
        let (p, _, _, _) = s.package(delivery);
        let bound = a::registration::register(&f.c(), &provision, &p).unwrap();
        local::validate_binding(&p, &bound, delivery).unwrap();
        assert!(bound.profile == profile);
        let repeated = a::registration::register(&f.c(), &provision, &p).unwrap();
        assert!(serde_json::to_value(&bound).unwrap() == serde_json::to_value(repeated).unwrap());
        let id = bound.manifest["package_id"].as_str().unwrap();
        let (data, secret) = f.candidate(id);
        let session = f.activate(&data, &bound.secret, &secret);
        assert_eq!(session["delivery"], delivery);
        assert_eq!(session["capabilities"], json!(["quote"]));
        let (another, _) = f.candidate(id);
        assert!(a::devices::enroll(&f.c(), &another, &bound.secret).is_err());
        assert!(a::devices::enroll(&f.c(), &data, &bound.secret).is_ok());
        a::packages::close(
            &f.c(),
            p.manifest["issuer_id"].as_str().unwrap(),
            id,
            &envelope(a::ISSUANCE, json!({})),
            true,
        )
        .unwrap();
        assert!(a::registration::register(&f.c(), &provision, &p).is_err());
        assert_eq!(a::packages::get(&f.c(), id).unwrap().1, "revoked");
        let mut wrong = bound.clone();
        wrong.manifest["capabilities"] = json!(["quote", "orders"]);
        assert!(local::validate_binding(&p, &wrong, delivery).is_err());
    }
}
#[test]
fn disabled_signer_is_not_reenabled_by_registration() {
    let s = Signer::new();
    let f = Fixture::new();
    let provision = s.provision();
    s.install_trust(&f, &provision);
    let (p, _, _, _) = s.package("sales");
    f.c()
        .execute(
            "UPDATE issuers SET enabled=0 WHERE id=?",
            [provision["issuer_id"].as_str().unwrap()],
        )
        .unwrap();
    assert!(a::registration::register(&f.c(), &provision, &p).is_err());
    assert_eq!(
        f.c()
            .query_row(
                "SELECT enabled FROM issuers WHERE id=?",
                [provision["issuer_id"].as_str().unwrap()],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
}
