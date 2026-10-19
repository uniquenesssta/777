//! Explicit schema-3 intake upgrade; ordinary ledgers remain schema 2.
use crate::{store, Error, Result};
use rusqlite::Connection;
use serde_json::{json, Value};
pub const DDL: &str = include_str!("schema.sql");
pub mod canonical;
mod validation;
pub const HASH: &str = "721dc11b48d5c45b2b4f5fcc512b730e2e6f36f266a86409a7a56439ed6c6bab";
pub const TABLES: [&str; 10] = [
    "offline_meta",
    "offline_streams",
    "offline_leases",
    "offline_operations",
    "offline_states",
    "offline_events",
    "offline_collisions",
    "offline_conflicts",
    "offline_resolutions",
    "order_changes_feed",
];
pub fn upgrade(c: &mut Connection) -> Result<()> {
    if store::verify(c)?["schema_version"] == 3 {
        return Ok(());
    }
    store::migrate(c)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    if store::verify(&tx)?["schema_version"] != 2 {
        return Err(Error::new("INVALID_DATABASE"));
    }
    tx.execute_batch(DDL)?;
    tx.execute(
        "INSERT INTO offline_meta VALUES(1,?,0,'{}')",
        [store::uid()?],
    )?;
    tx.execute(
        "UPDATE ledger_meta SET schema_version=3,schema_hash=? WHERE singleton=1",
        [HASH],
    )?;
    tx.execute_batch("PRAGMA user_version=3")?;
    store::verify(&tx)?;
    tx.commit()?;
    Ok(())
}
pub fn inventory(c: &Connection) -> Result<Value> {
    validation::originals(c)?;
    let (epoch, revision, keys): (String, i64, String) = c.query_row(
        "SELECT epoch,revision,public_keys_json FROM offline_meta WHERE id=1",
        [],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    )?;
    store::id(&epoch)?;
    let _: serde_json::Map<String, Value> = serde_json::from_str(&keys)?;
    let orphans: i64 = c.query_row("SELECT count(*) FROM offline_operations o LEFT JOIN offline_states s USING(operation_id) WHERE s.operation_id IS NULL", [], |r|r.get(0))?;
    if orphans != 0 {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let mut counts = serde_json::Map::new();
    for name in TABLES {
        counts.insert(
            name.into(),
            json!(
                c.query_row(&format!("SELECT count(*) FROM {name}"), [], |r| r
                    .get::<_, i64>(0))?
            ),
        );
    }
    Ok(json!({"epoch":epoch,"revision":revision,"counts":counts}))
}
