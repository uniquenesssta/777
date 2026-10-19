//! Conflict bases remain addressable after any later business revision.
use super::*;
use crate::{application::Order, editing};
use rusqlite::params;
pub(super) fn verify(c: &Connection) -> Result<()> {
    let mut st=c.prepare("SELECT o.order_id,f.base_json,f.current_json FROM offline_conflicts f JOIN offline_operations o USING(operation_id)")?;
    let mut rows = st.query([])?;
    while let Some(row) = rows.next()? {
        let oid: String = row.get(0)?;
        for col in [1, 2] {
            let reference: Value = serde_json::from_str(&row.get::<_, String>(col)?)?;
            if reference.is_null() {
                continue;
            }
            if reference["order_id"] != oid {
                return Err(Error::new("INVALID_DATABASE"));
            }
            let rev = reference["revision"]
                .as_str()
                .and_then(|s| s.parse::<i64>().ok())
                .filter(|n| *n > 0)
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?;
            let current = Order::read(c, &oid)?;
            let target = if rev == current.revision {
                current
            } else {
                let raw: String = c.query_row(
                    "SELECT snapshot_json FROM order_versions WHERE order_id=? AND revision=?",
                    params![oid, rev],
                    |r| r.get(0),
                )?;
                Order::from_snapshot(&editing::validate_archive(c, &oid, rev, &raw)?)?
            };
            if let Some(sha) = reference.get("sha256") {
                if *sha != store::hash(store::encoded(&serde_json::to_value(target)?)) {
                    return Err(Error::new("INVALID_DATABASE"));
                }
            } else if reference["snapshot_reference"] != true {
                return Err(Error::new("INVALID_DATABASE"));
            }
        }
    }
    Ok(())
}
