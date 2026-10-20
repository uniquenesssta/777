use super::super::{context::Context, leases, storage, Intake};
use super::{merge, plan};
use crate::{Error, Result};
use quote_ledger::{application::Order, store};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
pub(super) fn reference(order: Option<&Order>) -> Value {
    order.map_or(Value::Null,|o|json!({"order_id":o.order_id,"revision":o.revision.to_string(),"sha256":store::hash(store::encoded(&serde_json::to_value(o).unwrap()))}))
}
pub(crate) fn state(
    c: &Connection,
    id: &str,
    state: &str,
    reason: Option<&str>,
    request: Option<&str>,
) -> Result<()> {
    c.execute(
        "UPDATE offline_states SET state=?,reason=?,applied_request_id=? WHERE operation_id=?",
        params![state, reason, request, id],
    )?;
    c.execute(
        "INSERT INTO offline_events(operation_id,state,at) VALUES(?,?,?)",
        params![id, state, crate::auth::now()],
    )?;
    c.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
    if ["applied", "conflict", "rejected"].contains(&state) {
        wake(c, id)?;
    }
    Ok(())
}
/// Requeue a bounded number of direct dependents; immutable inputs stay untouched.
pub(crate) fn wake(c: &Connection, id: &str) -> Result<()> {
    let children = {
        let mut q = c.prepare("SELECT o.operation_id FROM offline_operations o JOIN offline_states s USING(operation_id) WHERE o.previous_operation_id=? AND s.state='waiting_dependency' ORDER BY o.operation_id LIMIT 16")?;
        let rows = q
            .query_map([id], |r| r.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    for child in children {
        c.execute(
            "UPDATE offline_states SET state='received',reason=NULL WHERE operation_id=?",
            [&child],
        )?;
        c.execute(
            "INSERT INTO offline_events(operation_id,state,at) VALUES(?,'received',?)",
            params![child, crate::auth::now()],
        )?;
        c.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
    }
    Ok(())
}
pub(super) fn preserve(
    c: &Connection,
    v: &Value,
    base: Option<&Order>,
    current: Option<&Order>,
    reason: &str,
) -> Result<()> {
    preserve_refs(c, v, reference(base), reference(current), reason)
}
fn preserve_refs(
    c: &Connection,
    v: &Value,
    base: Value,
    current: Value,
    reason: &str,
) -> Result<()> {
    let candidate = json!({"operation_id":v["operation_id"],"content_sha256":v["content_sha256"],"reason":reason});
    if storage::retained(c)? + store::encoded(&candidate).len() as i64 > 2147483648 {
        return Err(Error::new(429, "OFFLINE_QUEUE_CAPACITY"));
    }
    c.execute(
        "INSERT INTO offline_conflicts VALUES(?,?,?,?) ON CONFLICT(operation_id) DO NOTHING",
        params![
            v["operation_id"].as_str(),
            store::encoded(&base),
            store::encoded(&current),
            store::encoded(&candidate)
        ],
    )?;
    Ok(())
}

fn prepare(
    c: &Connection,
    v: &Value,
    lease: &Value,
) -> Result<(Option<Order>, Option<Order>, Order)> {
    let current = plan::current(c, v["order_id"].as_str().unwrap())?;
    let base = if v["kind"] == "create" {
        None
    } else {
        Some(plan::basis(
            c,
            v,
            current
                .as_ref()
                .ok_or_else(|| merge::conflict("ORDER_NOT_FOUND"))?,
        )?)
    };
    let candidate = plan::propose(
        v,
        base.as_ref(),
        lease["price_version_id"].as_str().unwrap(),
    )?;
    Ok((base, current, candidate))
}
pub(crate) fn apply(i: &Intake, c: &Connection, ctx: &Context, v: &Value) -> Result<bool> {
    let id = v["operation_id"].as_str().unwrap();
    let current_state: String = c.query_row(
        "SELECT state FROM offline_states WHERE operation_id=?",
        [id],
        |r| r.get(0),
    )?;
    if current_state != "received" {
        return Ok(false);
    }
    let lease = leases::read(i, c, ctx, v)?;
    if let Some(reason) = storage::reason(i, ctx, v, &lease) {
        state(c, id, "rejected", Some(reason), None)?;
        return Ok(true);
    }
    // Auth is revalidated by the caller while holding the shared authorization gate.
    let large:bool=c.query_row("SELECT EXISTS(SELECT 1 FROM orders WHERE order_id=? AND length(CAST(input_json AS BLOB))+length(CAST(details_json AS BLOB))>1048576)",[v["order_id"].as_str()],|r|r.get(0))?;
    if large {
        let revision: i64 = c.query_row(
            "SELECT revision FROM orders WHERE order_id=?",
            [v["order_id"].as_str()],
            |r| r.get(0),
        )?;
        let reference = json!({"order_id":v["order_id"],"revision":revision.to_string(),"snapshot_reference":true});
        preserve_refs(c, v, Value::Null, reference, "LARGE_ORDER_REQUIRES_REVIEW")?;
        state(c, id, "conflict", Some("LARGE_ORDER_REQUIRES_REVIEW"), None)?;
        return Ok(true);
    }
    let current = plan::current(c, v["order_id"].as_str().unwrap())?;
    let mut base = None;
    c.execute_batch("SAVEPOINT offline_business")?;
    let result = (|| -> Result<Value> {
        let issued = lease["issued_at"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(i64::MAX);
        let at = time::OffsetDateTime::parse(
            v["created_at"].as_str().unwrap(),
            &time::format_description::well_known::Rfc3339,
        )
        .map_err(|_| Error::new(422, "OFFLINE_TIME_INVALID"))?
        .unix_timestamp();
        if at < issued.saturating_sub(300) || at > crate::auth::now() + 300 {
            return Err(merge::conflict("BUSINESS_DATE_REQUIRES_REVIEW"));
        }
        quote_ledger::deletion::available(c, v["order_id"].as_str().unwrap())?;
        let (basis, observed, candidate) = prepare(c, v, &lease)?;
        base = basis;
        let kind = v["kind"].as_str().unwrap();
        let mut next = if kind == "create" {
            if observed.is_some() {
                return Err(merge::conflict("ORDER_ID_COLLISION"));
            }
            candidate
        } else {
            merge::merge(
                base.as_ref().unwrap(),
                observed.as_ref().unwrap(),
                &candidate,
                kind,
            )?
        };
        if (kind == "create" || kind == "edit") && plan::duplicate(c, &next)?.is_some() {
            return Err(merge::conflict("POSSIBLE_DUPLICATE_ORDER"));
        }
        if serde_json::to_vec(&next)?.len() > 1048576 {
            return Err(merge::conflict("LARGE_ORDER_REQUIRES_REVIEW"));
        }
        next.revision = observed.as_ref().map_or(0, |o| o.revision);
        let choice = plan::customer(c, &ctx.actor, &next, &v["payload"]["customer"])?;
        Ok(quote_ledger::application::apply(
            c,
            quote_ledger::application::Change {
                actor: &ctx.actor,
                request: id,
                fingerprint: v["content_sha256"].as_str().unwrap(),
                kind,
                order: &next,
                payload: &v["payload"],
                customer: &choice,
            },
        )?)
    })();
    match result {
        Ok(_) => {
            c.execute_batch("RELEASE offline_business")?;
            state(c, id, "applied", None, Some(id))?;
        }
        Err(e) => {
            c.execute_batch("ROLLBACK TO offline_business; RELEASE offline_business")?;
            if [403, 404, 409, 422].contains(&e.status) {
                preserve(c, v, base.as_ref(), current.as_ref(), &e.code)?;
                state(
                    c,
                    id,
                    if e.status == 403 {
                        "rejected"
                    } else {
                        "conflict"
                    },
                    Some(&e.code),
                    None,
                )?;
            } else {
                return Err(e);
            }
        }
    }
    Ok(true)
}
