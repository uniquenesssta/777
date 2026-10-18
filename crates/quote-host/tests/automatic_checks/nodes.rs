use crate::automatic_support::{envelope, Fixture};
use quote_host::{
    automatic as a,
    cluster::{api, membership, snapshot},
};
use quote_ledger::store;
use serde_json::json;
#[test]
fn node_join_is_separate_resumable_and_revocation_blocks_replication() {
    let mut f = Fixture::new();
    f.cluster();
    let (package, secret, _) = f.package("manager", &["quote"], 3);
    let (node_secret, node) = (a::secret().unwrap(), store::uid().unwrap());
    let p = a::trust::profile(&f.c()).unwrap();
    let data = envelope(
        a::ENROLLMENT,
        json!({"package_id":package,"site_id":p["site_id"],"ledger_id":f.ledger,"node_id":node,"node_secret_hash":a::digest(&node_secret).unwrap()}),
    );
    let permit = a::nodes::permit(&f.root, &f.c(), &data, &secret).unwrap();
    let again = a::nodes::permit(&f.root, &f.c(), &data, &secret).unwrap();
    assert_eq!(permit["permit"], again["permit"]);
    assert!(a::nodes::authorize(&f.c(), &node).is_err());
    let mut join = data.clone();
    join.as_object_mut().unwrap().remove("package_id");
    // Simulate interruption after peer commit but before activation commit.
    membership::automatic_peer(&f.root, &node, &a::digest(&node_secret).unwrap()).unwrap();
    assert!(a::nodes::authorize(&f.c(), &node).is_err());
    let result =
        a::nodes::enroll(&f.root, &f.c(), &join, permit["permit"].as_str().unwrap()).unwrap();
    a::nodes::enroll(&f.root, &f.c(), &join, permit["permit"].as_str().unwrap()).unwrap();
    assert_eq!(result["ledger_id"], f.ledger);
    membership::authenticate(&f.root, &node, &node_secret).unwrap();
    a::nodes::authorize(&f.c(), &node).unwrap();
    let config = quote_host::cluster::config::required(&f.root).unwrap();
    let request = json!({"node_id":node,"cluster_id":config.cluster_id,"ledger_id":f.ledger});
    let error = api::handle(
        &mut f.service,
        "POST",
        "/v1/cluster/manifest",
        &node_secret,
        &request,
        "fixture",
    )
    .unwrap_err();
    assert_eq!(error.code, "PROTOCOL_UPGRADE_REQUIRED");
    a::packages::close(
        &f.c(),
        &f.issuer,
        &package,
        &envelope(a::ISSUANCE, json!({})),
        true,
    )
    .unwrap();
    let mut request = request;
    request["snapshot_protocol"] = json!(snapshot::FORMAT_V2);
    assert!(api::handle(
        &mut f.service,
        "POST",
        "/v1/cluster/manifest",
        &node_secret,
        &request,
        "fixture"
    )
    .is_err());
    assert!(a::nodes::enroll(&f.root, &f.c(), &join, permit["permit"].as_str().unwrap()).is_err());
}
#[test]
fn sales_package_cannot_create_node_even_when_it_sends_manager_fields() {
    let f = Fixture::new();
    let (package, secret, _) = f.package("sales", &["quote"], 3);
    let p = a::trust::profile(&f.c()).unwrap();
    let mut data = envelope(
        a::ENROLLMENT,
        json!({"package_id":package,"site_id":p["site_id"],"ledger_id":f.ledger,"node_id":store::uid().unwrap(),"node_secret_hash":store::hash("fixture")}),
    );
    assert!(a::nodes::permit(&f.root, &f.c(), &data, &secret).is_err());
    data["delivery"] = json!("manager");
    assert!(a::nodes::permit(&f.root, &f.c(), &data, &secret).is_err());
}
#[test]
fn new_auth_snapshot_declares_compatibility_and_legacy_users_keep_their_ids() {
    let f = Fixture::new();
    f.cluster();
    let original =
        quote_ledger::integrity::inventory(&store::open(&f.service.ledger, false).unwrap())
            .unwrap();
    let config = quote_host::cluster::config::required(&f.root).unwrap();
    let p = snapshot::capture(&f.service, &config).unwrap().unwrap();
    let m = snapshot::read(&f.root, &p).unwrap();
    assert_eq!(m.format, snapshot::FORMAT_V2);
    snapshot::validate_data(&snapshot::folder(&f.root, &p).unwrap(), &m).unwrap();
    let mut wrong = m;
    wrong.format = snapshot::FORMAT.into();
    assert!(snapshot::validate_data(&snapshot::folder(&f.root, &p).unwrap(), &wrong).is_err());
    assert_eq!(
        original,
        quote_ledger::integrity::inventory(&store::open(&f.service.ledger, false).unwrap())
            .unwrap()
    );
    assert!(f.service.auth.authenticate(&f.legacy_token).is_ok());
}
#[test]
fn legacy_peer_adoption_requires_old_node_proof_and_preserves_id() {
    let f = Fixture::new();
    f.cluster();
    let config = quote_host::cluster::config::required(&f.root).unwrap();
    let invitation = membership::invite(&f.root).unwrap();
    let node = store::uid().unwrap();
    let credential = a::secret().unwrap();
    membership::enroll(&f.root,&json!({"cluster_id":config.cluster_id,"ledger_id":f.ledger,"grant_id":invitation["grant_id"],"ticket":invitation["ticket"],"node_id":node,"credential":credential})).unwrap();
    let (package, secret, _) = f.package("manager", &["quote"], 3);
    let p = a::trust::profile(&f.c()).unwrap();
    let data = envelope(
        a::ENROLLMENT,
        json!({"package_id":package,"site_id":p["site_id"],"ledger_id":f.ledger,"node_id":node,"node_secret_hash":a::digest(&credential).unwrap()}),
    );
    assert!(a::nodes::permit(&f.root, &f.c(), &data, &secret).is_err());
    assert!(a::nodes::adopt(&f.root, &f.c(), &data, &a::secret().unwrap(), &secret).is_err());
    let adopted = a::nodes::adopt(&f.root, &f.c(), &data, &credential, &secret).unwrap();
    assert_eq!(adopted["node_id"], node);
    a::nodes::adopt(&f.root, &f.c(), &data, &credential, &secret).unwrap();
    assert_eq!(
        membership::listing(&f.root)
            .unwrap()
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
