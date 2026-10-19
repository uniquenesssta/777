//! Explicit local maintenance provisioning. Never called by formal startup.
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use ring::rand::SystemRandom;
use rusqlite::params;
use serde_json::json;
pub fn provision(s: &Service) -> Result<Value> {
    require_local(&s.ledger)?;
    if crate::cluster::config::read(&s.root)?
        .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
    {
        return Err(Error::new(409, "CLUSTER_REPLICA_CANNOT_WRITE"));
    }
    let profile = crate::automatic::trust::profile(&s.auth.connection()?)?;
    if let Some(i) = Intake::open(s)? {
        return Ok(
            json!({"status":"intake_already_prepared","ledger_id":i.config["ledger_id"],"offline_orders":false}),
        );
    }
    super::resources::check(s)?;
    let private = s.root.join("private");
    let before = private.join("ledger-before-offline.sqlite3");
    if !before.exists() {
        quote_ledger::integrity::backup(&s.ledger, &before)?;
    }
    if quote_ledger::integrity::inventory(&store::open(&before, false)?)?["ledger_id"]
        != s.config["ledger_id"]
    {
        return Err(Error::new(409, "HOST_STORE_IDENTITY_CONFLICT"));
    }
    let key_path = private.join("offline-signing.pk8");
    if !key_path.exists() {
        let key = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new())
            .map_err(|_| Error::new(503, "OFFLINE_SIGNING_KEY_UNAVAILABLE"))?;
        files::new_file(&key_path, key.as_ref())?;
    }
    let key = Ed25519KeyPair::from_pkcs8(&files::read(&key_path, 4096)?)
        .map_err(|_| Error::new(503, "OFFLINE_SIGNING_KEY_INVALID"))?;
    let kid = store::hash(key.public_key().as_ref());
    let mut c = store::open(&s.ledger, true)?;
    quote_ledger::intake::upgrade(&mut c)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let raw: String = tx.query_row(
        "SELECT public_keys_json FROM offline_meta WHERE id=1",
        [],
        |r| r.get(0),
    )?;
    let mut keys: Value = serde_json::from_str(&raw)?;
    keys[&kid] = json!(STANDARD.encode(key.public_key().as_ref()));
    let epoch = store::uid()?;
    tx.execute(
        "UPDATE offline_meta SET epoch=?,revision=revision+1,public_keys_json=? WHERE id=1",
        params![epoch, store::encoded(&keys)],
    )?;
    tx.commit()?;
    let config = json!({"format":FORMAT,"mode":"receive_only","site_id":profile["site_id"],"ledger_id":s.config["ledger_id"],"key_id":kid,"epoch":epoch});
    files::replace_json(&private.join("offline-intake.json"), &config)?;
    Intake::open(s)?.ok_or_else(|| Error::new(503, "OFFLINE_INTAKE_CONFIGURATION_INVALID"))?;
    Ok(
        json!({"status":"intake_prepared_restart_required","ledger_id":s.config["ledger_id"],"offline_orders":false}),
    )
}
pub(super) fn require_local(path: &std::path::Path) -> Result<()> {
    #[cfg(windows)]
    {
        use std::path::{Component, Prefix};
        let canonical = path.canonicalize()?;
        if matches!(canonical.components().next(),Some(Component::Prefix(p)) if matches!(p.kind(),Prefix::UNC(..)|Prefix::VerbatimUNC(..)))
        {
            return Err(Error::new(422, "OFFLINE_LOCAL_STORAGE_REQUIRED"));
        }
    }
    #[cfg(not(windows))]
    let _ = path;
    Ok(())
}
pub fn enable(
    root: &std::path::Path,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    let _owner = files::Owner::acquire(root)?;
    let mut s = Service::load(root, auxiliary, true)?;
    let login = s
        .auth
        .login(&json!(user), &json!(password), "offline-intake-maintenance")?;
    let token = login["token"].as_str().unwrap();
    let result = (|| {
        crate::auth::Auth::admin(&s.auth.authenticate(token)?)?;
        provision(&s)
    })();
    let _ = s.auth.logout(token);
    result
}
