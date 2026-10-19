use super::super::{capacity, Intake, FORMAT};
use crate::{protocol::fields, Error, Result};
use quote_ledger::store;
use rusqlite::params;
use serde_json::{json, Value};
pub(super) fn handle(
    i: &Intake,
    method: &str,
    path: &str,
    token: &str,
    data: &Value,
) -> Result<Value> {
    let actor = super::authorization::reviewer(i, token)?;
    let _guard = capacity::begin(&i.capacity, &format!("review:{}", actor.subject))?;
    if method != "POST" {
        return Err(Error::new(405, "METHOD_NOT_ALLOWED"));
    }
    if data["protocol"] != FORMAT {
        return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
    }
    if path == "/v1/offline/resolve" {
        return super::resolution::resolve(i, &actor, data);
    }
    if path == "/v1/offline/review-chunk" {
        return super::review_read::chunk(i, data);
    }
    if path != "/v1/offline/review" {
        return Err(Error::new(404, "NOT_FOUND"));
    }
    fields(data, &["protocol", "after"], &[])?;
    let after = if data["after"].is_null() {
        ""
    } else {
        super::super::envelope::uuid(&data["after"])?
    };
    let c = store::open(&i.ledger, false)?;
    c.execute_batch("BEGIN")?;
    let mut st=c.prepare("SELECT o.operation_id,o.operation_json,s.state,s.reason,f.base_json,f.current_json FROM offline_operations o JOIN offline_states s USING(operation_id) LEFT JOIN offline_conflicts f USING(operation_id) LEFT JOIN offline_resolutions r USING(operation_id) WHERE o.operation_id>? AND s.state IN ('conflict','rejected') AND r.operation_id IS NULL ORDER BY o.operation_id LIMIT 33")?;
    let rows = st
        .query_map(params![after], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let mut items = Vec::new();
    let mut size = 0;
    let mut next = after.to_owned();
    let mut more = false;
    for (id, raw, state, reason, base, current) in rows {
        let item = json!({"operation":serde_json::from_str::<Value>(&raw)?,"state":state,"reason":reason,"base":base.map(|s|serde_json::from_str::<Value>(&s)).transpose()?,"current":current.map(|s|serde_json::from_str::<Value>(&s)).transpose()?});
        let bytes = serde_json::to_vec(&item)?.len();
        if items.len() == 32 || size + bytes > 900000 {
            more = true;
            break;
        }
        size += bytes;
        next = id;
        items.push(item);
    }
    Ok(json!({"protocol":FORMAT,"items":items,"next_after":if more{json!(next)}else{Value::Null}}))
}
