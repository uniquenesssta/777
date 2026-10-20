mod business;
mod finance;
mod receipts;
mod trust;
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use ring::signature::{Ed25519KeyPair, KeyPair};
struct Fixture {
    root: std::path::PathBuf,
    local: Local,
    binding: Binding,
    lease: Value,
    catalog: Value,
}
impl Fixture {
    fn new() -> Self {
        Self::with_finance(false)
    }
    fn with_finance(finance: bool) -> Self {
        let root = std::env::temp_dir().join(format!(
            "777-local-offline-{}",
            crate::types::new_id().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let local = Local::open(root.join("offline.sqlite3"), !cfg!(windows)).unwrap();
        let mut binding = Binding {
            site: crate::types::new_id().unwrap(),
            ledger: crate::types::new_id().unwrap(),
            device: crate::types::new_id().unwrap(),
            package: crate::types::new_id().unwrap(),
            subject: crate::types::new_id().unwrap(),
            pin: "a".repeat(64),
            role: "sales".into(),
            capabilities: vec!["edit_orders".into(), "orders".into(), "quote".into()],
        };
        let catalog = json!({"price_version_id":"local-fixture","rule_version":"business-v1","numeric_profile":"numeric-v1","items":[{"product_id":"item","sale":"10","k":"1","single":true,"unit_sale":"10"}]});
        let catalog = if finance {
            binding.role = "admin".into();
            binding.capabilities.insert(1, "finance".into());
            json!({"price_version_id":"local-fixture","rule_version":"business-v1","numeric_profile":"numeric-v1","pricing_mode_version":"final-unit-v1","items":[{"product_id":"item","sale":"0","cost":"4","k":"2.5","single":true,"pricing_mode":"cost_plus","unit_sale":"10"}]})
        } else {
            catalog
        };
        let mut public_catalog = catalog.clone();
        crate::permissions::redact_financial(&mut public_catalog);
        public_catalog
            .as_object_mut()
            .unwrap()
            .remove("pricing_mode_version");
        let body = json!({"format":"777-offline-lease-v1","lease_id":crate::types::new_id().unwrap(),"site_id":binding.site,"ledger_id":binding.ledger,"device_id":binding.device,"stream_id":crate::types::new_id().unwrap(),"subject":binding.subject,"package_id":binding.package,"capabilities":binding.capabilities,"price_version_id":"local-fixture","price_sha256":quote_ledger::store::hash(canonical(&public_catalog).unwrap()),"rule_version":"business-v1","numeric_profile":"numeric-v1","issued_at":now().to_string(),"expires_at":(now()+2592000).to_string(),"epoch":crate::types::new_id().unwrap(),"device_epoch":"1","user_epoch":"1"});
        let key = Ed25519KeyPair::from_pkcs8(
            Ed25519KeyPair::generate_pkcs8(&ring::rand::SystemRandom::new())
                .unwrap()
                .as_ref(),
        )
        .unwrap();
        let signature = key.sign(
            &[
                b"777-offline-lease-v1\n".as_slice(),
                &canonical(&body).unwrap(),
            ]
            .concat(),
        );
        let lease = json!({"body":body,"public_key":STANDARD.encode(key.public_key().as_ref()),"signature":STANDARD.encode(signature.as_ref())});
        local.prepare(&binding, &lease, &catalog).unwrap();
        Self {
            root,
            local,
            binding,
            lease,
            catalog,
        }
    }
    fn body(&self) -> Value {
        json!({"snapshot":{"price_version_id":"local-fixture","lines":[{"line_kind":"normal","product_id":"item","q":"1","h":"","w":"","name":""}]},"sources":[null],"order_id":null,"expected_revision":null,"details":{"customer":"buyer","order_ref":"order-one","wechat":"contact"},"customer":{}})
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let connection = std::mem::replace(
            &mut self.local.c,
            rusqlite::Connection::open_in_memory().unwrap(),
        );
        drop(connection);
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
