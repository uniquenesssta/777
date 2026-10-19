//! Durable dependency review; explicit application mode also commits ready business changes.
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
    if application::enabled(i) && state == "rejected" {
        application::wake(c, id)?;
    }
    Ok(true)
}
pub(super) fn scan(i: &Intake, cursor: &mut String) -> Result<bool> {
    let mut c = store::open(&i.ledger, true)?;
    let applying = application::enabled(i);
    let ready: bool = applying
        && c.query_row(
            "SELECT EXISTS(SELECT 1 FROM offline_states WHERE state='received')",
            [],
            |r| r.get(0),
        )?;
    let rows = {
        let sql = if ready {
            "SELECT o.operation_json,d.device_id,s.state FROM offline_states s JOIN offline_operations o USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE s.state='received' AND o.operation_id>? ORDER BY o.operation_id LIMIT 4"
        } else if applying {
            "SELECT o.operation_json,d.device_id,s.state FROM offline_states s JOIN offline_operations o USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE s.state='waiting_dependency' AND o.operation_id>? ORDER BY o.operation_id LIMIT 16"
        } else {
            "SELECT o.operation_json,d.device_id,s.state FROM offline_operations o JOIN offline_states s USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE o.operation_id>? AND s.state IN ('received','waiting_dependency') ORDER BY o.operation_id LIMIT 16"
        };
        let mut st = c.prepare(sql)?;
        let rows = st
            .query_map([if ready { "" } else { cursor.as_str() }], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    if rows.is_empty() {
        cursor.clear();
        return Ok(false);
    }
    let mut changed = false;
    for (raw, device, initial_state) in rows {
        let v: Value = serde_json::from_str(&raw)?;
        if !applying || initial_state == "waiting_dependency" {
            *cursor = v["operation_id"].as_str().unwrap().into();
        }
        let ctx = context::device(i, &device);
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        match ctx {
            Ok(ctx) => {
                changed |= refresh(i, &tx, &ctx, &v)?;
                if super::application::enabled(i) {
                    changed |= super::application::apply(i, &tx, &ctx, &v)?;
                }
            }
            Err(error) if error.status == 401 || error.status == 403 => {
                super::application::engine_state(
                    &tx,
                    v["operation_id"].as_str().unwrap(),
                    "rejected",
                    Some("AUTHORIZATION_REQUIRES_REVIEW"),
                    None,
                )?;
                changed = true;
            }
            Err(error) => return Err(error),
        }
        super::fault(i, "application_before_commit");
        tx.commit()?;
        super::fault(i, "application_after_commit");
    }
    Ok(changed)
}
