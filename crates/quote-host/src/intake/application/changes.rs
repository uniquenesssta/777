use super::super::{context::Context, Intake, FORMAT};
use crate::{automatic::permissions, protocol, Error, Result};
use quote_ledger::store;
use rusqlite::params;
use serde_json::{json, Value};
pub(crate) fn handle(i: &Intake, ctx: &Context, path: &str, data: &Value) -> Result<Value> {
    if !super::enabled(i) {
        return Err(Error::new(426, "OFFLINE_APPLICATION_NOT_ENABLED"));
    }
    permissions::require(&ctx.capabilities, "orders")?;
    if data["protocol"] != FORMAT {
        return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
    }
    if path == "/v1/offline/order-chunk" {
        return super::projection::chunk(i, ctx, data);
    }
    if path == "/v1/offline/diff-chunk" {
        return super::history::chunk(i, ctx, data);
    }
    protocol::fields(data, &["protocol", "cursor"], &[])?;
    let after = super::cursor::decode(i, ctx, &data["cursor"])?;
    let c = store::open(&i.ledger, false)?;
    c.execute_batch("BEGIN")?;
    let maximum: i64 = c.query_row(
        "SELECT coalesce(max(change_id),0) FROM order_changes_feed",
        [],
        |r| r.get(0),
    )?;
    if after > maximum {
        return Err(Error::new(409, "OFFLINE_CURSOR_REBUILD_REQUIRED"));
    }
    let mut st=c.prepare("SELECT f.change_id,f.order_id,f.order_revision,o.revision,o.state FROM order_changes_feed f JOIN orders o USING(order_id) WHERE f.change_id>? AND (?='admin' OR f.owner_id=?) ORDER BY f.change_id LIMIT 101")?;
    let rows = st
        .query_map(params![after, ctx.actor.role, ctx.actor.subject], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, String>(4)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let more = rows.len() > 100;
    let mut next = after;
    let mut items = Vec::new();
    for (seq, id, version, current, state) in rows.into_iter().take(100) {
        next = seq;
        items.push(json!({"change_id":seq.to_string(),"order_id":id,"event_revision":version.to_string(),"order_revision":current.to_string(),"state":state}));
    }
    if !more {
        next = maximum;
    }
    Ok(
        json!({"protocol":FORMAT,"epoch":i.config["epoch"],"changes":items,"cursor":super::cursor::encode(i,ctx,next),"has_more":more}),
    )
}
