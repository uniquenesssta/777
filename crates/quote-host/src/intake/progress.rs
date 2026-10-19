//! Durable dependency and authorization review; does not apply business orders in stage B.
use super::{context::Context, *};
use rusqlite::{params, Connection, OptionalExtension};
pub(super) fn refresh(i: &Intake, c: &Connection, ctx: &Context, v: &Value) -> Result<bool> {
    let id = v["operation_id"].as_str().unwrap();
    let old: (String, Option<String>) = c.query_row(
        "SELECT state,reason FROM offline_states WHERE operation_id=?",
        [id],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    if ["applied", "conflict", "rejected"].contains(&old.0.as_str()) {
        return Ok(false);
    }
    let lease = leases::read(i, c, ctx, v)?;
    let mut reason = storage::reason(i, ctx, v, &lease).map(str::to_owned);
    if reason.is_none() {
        if let Err(error) = storage::dependency(c, v, &[]) {
            if error.status == 409 || error.status == 422 {
                reason = Some("DEPENDENCY_REQUIRES_REVIEW".into());
            } else {
                return Err(error);
            }
        }
    }
    let mut state = if reason.is_some() {
        "rejected"
    } else {
        "received"
    };
    if reason.is_none() {
        if let Some(previous) = v["base"]["previous_operation_id"].as_str() {
            let parent: Option<String> = c
                .query_row(
                    "SELECT state FROM offline_states WHERE operation_id=?",
                    [previous],
                    |r| r.get(0),
                )
                .optional()?;
            if parent.as_deref() != Some("applied") {
                let received: i64 = c.query_row(
                    "SELECT received_at FROM offline_operations WHERE operation_id=?",
                    [id],
                    |r| r.get(0),
                )?;
                if matches!(parent.as_deref(), Some("conflict" | "rejected")) {
                    state = "rejected";
                    reason = Some("PREDECESSOR_REQUIRES_REVIEW".into());
                } else if parent.is_none() && crate::auth::now() - received >= 86400 {
                    state = "rejected";
                    reason = Some("MISSING_DEPENDENCY_REQUIRES_REVIEW".into());
                } else {
                    state = "waiting_dependency";
                    reason = Some(
                        if parent.is_none() {
                            "MISSING_DEPENDENCY"
                        } else {
                            "PREDECESSOR_NOT_APPLIED"
                        }
                        .into(),
                    );
                }
            }
        }
    }
    if old.0 == state && old.1 == reason {
        return Ok(false);
    }
    c.execute(
        "UPDATE offline_states SET state=?,reason=? WHERE operation_id=?",
        params![state, reason, id],
    )?;
    c.execute(
        "INSERT INTO offline_events(operation_id,state,at) VALUES(?,?,?)",
        params![id, state, crate::auth::now()],
    )?;
    c.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
    Ok(true)
}
pub(super) fn scan(i: &Intake, cursor: &mut String) -> Result<bool> {
    let mut c = store::open(&i.ledger, true)?;
    let rows = {
        let mut st=c.prepare("SELECT o.operation_json,d.device_id FROM offline_operations o JOIN offline_states s USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE o.operation_id>? AND s.state IN ('received','waiting_dependency') ORDER BY o.operation_id LIMIT 16")?;
        let rows = st
            .query_map([cursor.as_str()], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    if rows.is_empty() {
        cursor.clear();
        return Ok(false);
    }
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let mut changed = false;
    for (raw, device) in rows {
        let v: Value = serde_json::from_str(&raw)?;
        *cursor = v["operation_id"].as_str().unwrap().into();
        match context::device(i, &device) {
            Ok(ctx) => changed |= refresh(i, &tx, &ctx, &v)?,
            Err(error) if error.status == 401 || error.status == 403 => {
                let id = v["operation_id"].as_str().unwrap();
                tx.execute("UPDATE offline_states SET state='rejected',reason='AUTHORIZATION_REQUIRES_REVIEW' WHERE operation_id=?",[id])?;
                tx.execute(
                    "INSERT INTO offline_events(operation_id,state,at) VALUES(?,'rejected',?)",
                    params![id, crate::auth::now()],
                )?;
                tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
                changed = true;
            }
            Err(error) => return Err(error),
        }
    }
    tx.commit()?;
    Ok(changed)
}
