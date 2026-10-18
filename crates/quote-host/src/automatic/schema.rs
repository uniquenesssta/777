use crate::{auth, fail, files, Result};
use rusqlite::{Connection, OpenFlags};
use std::path::Path;
pub const EXTRA: &str = include_str!("schema.sql");
pub fn version(path: &Path) -> Result<i64> {
    files::local(path, true)?;
    let c = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    Ok(c.query_row("PRAGMA user_version", [], |r| r.get(0))?)
}
pub fn enabled(c: &Connection) -> Result<bool> {
    Ok(c.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0))? == 2)
}
pub fn upgrade(path: &Path) -> Result<()> {
    let mut c = files::database(path, auth::APP, auth::DDL)?;
    if enabled(&c)? {
        return Ok(());
    }
    // A complete, validated pre-migration auth snapshot remains beside the private DB.
    let backup = path.with_file_name("auth-before-automatic.sqlite3");
    if !backup.exists() {
        let stage = path.with_file_name(format!(
            "auth-upgrade-{}.partial",
            quote_ledger::store::uid()?
        ));
        let result: Result<()> = (|| {
            files::snapshot(path, &stage, auth::APP, auth::DDL)?;
            files::database(&stage, auth::APP, auth::DDL)?;
            std::fs::rename(&stage, &backup)?;
            Ok(())
        })();
        if stage.exists() {
            let _ = std::fs::remove_file(stage);
        }
        result?;
    } else {
        files::database(&backup, auth::APP, auth::DDL)?;
    }
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    if tx.query_row("PRAGMA quick_check", [], |r| r.get::<_, String>(0))? != "ok" {
        return fail(503, "AUTH_SCHEMA_INVALID");
    }
    tx.execute_batch(EXTRA)?;
    tx.execute_batch("INSERT INTO principal_modes SELECT id,'legacy_password' FROM users; PRAGMA user_version=2;")?;
    tx.commit()?;
    files::database(path, auth::APP, auth::DDL)?;
    Ok(())
}
