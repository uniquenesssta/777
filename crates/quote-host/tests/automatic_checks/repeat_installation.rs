//! Old one-device manifests remain usable without rewriting their signed contents.
use crate::automatic_support::{envelope, Fixture};
use quote_host::automatic as a;
use quote_ledger::store;
use serde_json::{json, Value};

#[test]
fn old_one_device_package_enrolls_multiple_computers_with_original_permissions() {
    for delivery in ["manager", "sales"] {
        let mut f = Fixture::new();
        let permissions = if delivery == "manager" {
            vec!["quote", "orders", "finance", "prices"]
        } else {
            vec!["quote", "orders"]
        };
        let (package, secret, issued) = f.package(delivery, &permissions, 1);
        let (first, first_secret) = f.candidate(&package);
        let (second, second_secret) = f.candidate(&package);
        let first_session = f.activate(&first, &secret, &first_secret);
        let second_session = f.activate(&second, &secret, &second_secret);
        assert_ne!(first_session["subject"], second_session["subject"]);
        assert_eq!(second_session["delivery"], delivery);
        assert_eq!(
            second_session["capabilities"],
            first_session["capabilities"]
        );
        let body = json!({"request_id":store::uid().unwrap(),"expected_price_version_id":null,"prices":{"price_version_id":"second-computer","items":[{"product_id":"P","sale":"10","cost":"4","k":"1","single":true}]}});
        let token = second_session["token"].as_str().unwrap();
        let publication = f
            .service
            .handle("POST", "/v1/prices", token, &body, "", "fixture");
        if delivery == "manager" {
            publication.unwrap();
            let prices = f
                .service
                .handle("GET", "/v1/prices", token, &Value::Null, "", "fixture")
                .unwrap();
            assert_eq!(prices["items"][0]["product_id"], "P");
        } else {
            assert!(publication.is_err());
        }
        assert_eq!(
            a::packages::listing(&f.c(), &f.issuer, &package).unwrap()["manifest"],
            issued["manifest"]
        );
        assert!(
            a::devices::enroll(&f.c(), &f.candidate(&package).0, &a::secret().unwrap()).is_err()
        );
        a::packages::close(
            &f.c(),
            &f.issuer,
            &package,
            &envelope(a::ISSUANCE, json!({})),
            true,
        )
        .unwrap();
        assert!(a::devices::enroll(&f.c(), &f.candidate(&package).0, &secret).is_err());
    }
}

#[test]
fn repeated_manager_node_installation_is_not_capped_by_old_package_quota() {
    let f = Fixture::new();
    f.cluster();
    let (package, secret, _) = f.package("manager", &["quote"], 1);
    let profile = a::trust::profile(&f.c()).unwrap();
    for _ in 0..3 {
        let data = envelope(
            a::ENROLLMENT,
            json!({"package_id":package,"site_id":profile["site_id"],"ledger_id":f.ledger,"node_id":store::uid().unwrap(),"node_secret_hash":store::hash(a::secret().unwrap())}),
        );
        a::nodes::permit(&f.root, &f.c(), &data, &secret).unwrap();
    }
    assert_eq!(
        a::packages::listing(&f.c(), &f.issuer, &package).unwrap()["nodes"],
        3
    );
}
