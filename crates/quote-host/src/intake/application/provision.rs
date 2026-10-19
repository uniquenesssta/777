//! Explicit stopped-host controls. No formal package grants reviewer authority.
use crate::{auth::Auth, files, service::Service, Error, Result};
use quote_ledger::store;
use serde_json::{json, Value};
pub fn enable(
    root: &std::path::Path,
    user: &str,
    password: &str,
    auxiliary: bool,
) -> Result<Value> {
    maintain(root, user, password, auxiliary, |s| {
        super::super::setup::provision(s)?;
        super::super::resources::check(s)?;
        let path = s.root.join("private/offline-intake.json");
        let mut cfg = files::read_json(&path)?;
        if cfg["mode"] == "apply" {
            return Ok(
                json!({"status":"offline_application_already_prepared","offline_orders":false}),
            );
        }
        let c = store::open(&s.ledger, true)?;
        let tx = c.unchecked_transaction()?;
        tx.execute("INSERT INTO order_changes_feed(order_id,order_revision,owner_id,created_at) SELECT o.order_id,o.revision,o.owner_id,? FROM orders o WHERE NOT EXISTS(SELECT 1 FROM order_changes_feed f WHERE f.order_id=o.order_id)",[crate::auth::now()])?;
        tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
        tx.commit()?;
        cfg["mode"] = json!("apply");
        files::replace_json(&path, &cfg)?;
        Ok(json!({"status":"offline_application_prepared_restart_required","offline_orders":false}))
    })
}
pub fn reviewer(
    root: &std::path::Path,
    user: &str,
    password: &str,
    reviewer: &str,
    enabled: bool,
    auxiliary: bool,
) -> Result<Value> {
    maintain(root, user, password, auxiliary, |s| {
        let c = s.auth.connection()?;
        let name = crate::auth::username(&json!(reviewer))?;
        let (subject,epoch):(String,i64)=c.query_row("SELECT u.id,u.epoch FROM users u JOIN principal_modes m ON m.subject=u.id WHERE u.username=? AND u.enabled=1 AND u.role='admin' AND m.mode='legacy_password'",[name],|r|Ok((r.get(0)?,r.get(1)?)))?;
        let cfg = files::read_json(&s.root.join("private/offline-intake.json"))?;
        let path = s.root.join("private/offline-reviewers.json");
        let mut grants = if path.exists() {
            files::read_json(&path)?
        } else {
            json!({"format":"777-offline-reviewers-v1","ledger_id":cfg["ledger_id"],"epoch":cfg["epoch"],"reviewers":{}})
        };
        if grants["ledger_id"] != cfg["ledger_id"] || grants["epoch"] != cfg["epoch"] {
            return Err(Error::new(409, "OFFLINE_REVIEWER_EPOCH_CONFLICT"));
        }
        if enabled {
            grants["reviewers"][&subject] = json!(epoch);
        } else {
            grants["reviewers"]
                .as_object_mut()
                .unwrap()
                .remove(&subject);
        }
        files::replace_json(&path, &grants)?;
        Ok(json!({"status":"offline_reviewer_updated","subject":subject,"enabled":enabled}))
    })
}
fn maintain<F>(
    root: &std::path::Path,
    user: &str,
    password: &str,
    auxiliary: bool,
    work: F,
) -> Result<Value>
where
    F: FnOnce(&Service) -> Result<Value>,
{
    let _owner = files::Owner::acquire(root)?;
    if crate::cluster::config::read(root)?
        .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
    {
        return Err(Error::new(409, "CLUSTER_REPLICA_CANNOT_WRITE"));
    }
    let mut s = Service::load(root, auxiliary, true)?;
    let login = s.auth.login(
        &json!(user),
        &json!(password),
        "offline-application-maintenance",
    )?;
    let token = login["token"].as_str().unwrap();
    let result = (|| {
        Auth::admin(&s.auth.authenticate(token)?)?;
        work(&s)
    })();
    let _ = s.auth.logout(token);
    result
}
