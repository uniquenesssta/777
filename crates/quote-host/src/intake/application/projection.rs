//! Bounded current-order sections; never copy a whole ledger into a sales device.
use super::super::{context::Context, envelope, Intake, FORMAT};
use crate::{automatic::permissions, protocol, Error, Result};
use quote_ledger::store;
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
pub(super) fn chunk(i: &Intake, ctx: &Context, data: &Value) -> Result<Value> {
    protocol::fields(
        data,
        &[
            "protocol", "epoch", "order_id", "revision", "section", "offset",
        ],
        &[],
    )?;
    if data["epoch"] != i.config["epoch"] {
        return Err(Error::new(409, "OFFLINE_CURSOR_REBUILD_REQUIRED"));
    }
    let id = envelope::uuid(&data["order_id"])?;
    let revision = envelope::sequence(&data["revision"])?;
    let offset = protocol::text(&data["offset"], 19, true)?
        .parse::<i64>()
        .ok()
        .filter(|n| *n >= 0)
        .ok_or_else(|| Error::new(422, "INVALID_FIELDS"))?;
    let c = store::open(&i.ledger, false)?;
    c.execute_batch("BEGIN")?;
    let row:Option<(String,Value)>=c.query_row("SELECT owner_id,revision,state,price_id,created_at,details_json,income_cents,cost_cents,profit_cents,customer_id FROM orders WHERE order_id=?",[id],|r|Ok((r.get(0)?,json!({"order_id":id,"revision":r.get::<_,i64>(1)?.to_string(),"state":r.get::<_,String>(2)?,"price_version_id":r.get::<_,String>(3)?,"created_at":r.get::<_,String>(4)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(5)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(6)?.to_string(),"cost_cents":r.get::<_,i64>(7)?.to_string(),"profit_cents":r.get::<_,i64>(8)?.to_string(),"customer_id":r.get::<_,Option<String>>(9)?})))).optional()?;
    let (owner, mut header) = row.ok_or_else(|| Error::new(404, "NOT_FOUND"))?;
    if ctx.actor.role != "admin" && owner != ctx.actor.subject {
        return Err(Error::new(404, "NOT_FOUND"));
    }
    if header["revision"]
        .as_str()
        .and_then(|s| s.parse::<i64>().ok())
        != Some(revision)
    {
        return Err(Error::new(409, "REVISION_OR_PRICE_CONFLICT"));
    }
    header["deleted"] = json!(quote_ledger::deletion::deleted(&c, id)?);
    let section = protocol::text(&data["section"], 16, true)?;
    let rows = match section {
        "lines" => {
            let mut st=c.prepare("SELECT line_id,sequence,raw_json,normalized_json,income_cents,cost_cents,profit_cents,subtotal_before_cents,price_version_id FROM lines WHERE order_id=? ORDER BY sequence LIMIT 65 OFFSET ?")?;
            let records=st.query_map(params![id,offset],|r|Ok(json!({"line_id":r.get::<_,String>(0)?,"sequence":r.get::<_,i64>(1)?.to_string(),"raw":serde_json::from_str::<Value>(&r.get::<_,String>(2)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"normalized":serde_json::from_str::<Value>(&r.get::<_,String>(3)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(4)?.to_string(),"cost_cents":r.get::<_,i64>(5)?.to_string(),"profit_cents":r.get::<_,i64>(6)?.to_string(),"subtotal_before_cents":r.get::<_,i64>(7)?.to_string(),"price_version_id":r.get::<_,Option<String>>(8)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
            records
        }
        "notes" => {
            let mut st=c.prepare("SELECT note_id,author_id,body,created_at FROM notes WHERE order_id=? ORDER BY created_at,note_id LIMIT 65 OFFSET ?")?;
            let records=st.query_map(params![id,offset],|r|Ok(json!({"note_id":r.get::<_,String>(0)?,"author":r.get::<_,String>(1)?,"body":r.get::<_,String>(2)?,"created_at":r.get::<_,String>(3)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
            records
        }
        "history" => {
            let mut st=c.prepare("SELECT v.revision,v.created_at,json_extract(v.snapshot_json,'$.order.details_json'),json_extract(v.snapshot_json,'$.order.income_cents'),json_extract(v.snapshot_json,'$.order.cost_cents'),json_extract(v.snapshot_json,'$.order.profit_cents') FROM order_versions v WHERE v.order_id=? AND EXISTS(SELECT 1 FROM audit_events a WHERE a.order_id=v.order_id AND a.operation='save_order' AND a.before_json=v.snapshot_json) ORDER BY v.revision DESC LIMIT 65 OFFSET ?")?;
            let records=st.query_map(params![id,offset],|r|Ok(json!({"revision":r.get::<_,i64>(0)?.to_string(),"created_at":r.get::<_,String>(1)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(2)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(3)?.to_string(),"cost_cents":r.get::<_,i64>(4)?.to_string(),"profit_cents":r.get::<_,i64>(5)?.to_string()})))?.collect::<std::result::Result<Vec<_>,_>>()?;
            records
        }
        _ => return Err(Error::new(422, "INVALID_FIELDS")),
    };
    let mut items = Vec::new();
    let mut size = serde_json::to_vec(&header)?.len();
    let mut more = false;
    for mut row in rows {
        if !ctx.capabilities.iter().any(|c| c == "finance") {
            permissions::redact(&mut row);
            if let Some(normalized) = row.get_mut("normalized") {
                protocol::normalized(
                    normalized,
                    &store::Actor {
                        subject: ctx.actor.subject.clone(),
                        role: "sales".into(),
                    },
                );
            }
        }
        let bytes = serde_json::to_vec(&row)?.len();
        if items.len() == 64 || size + bytes > 900000 {
            more = true;
            break;
        }
        size += bytes;
        items.push(row);
    }
    if !ctx.capabilities.iter().any(|c| c == "finance") {
        permissions::redact(&mut header)
    }
    let next = offset + items.len() as i64;
    Ok(
        json!({"protocol":FORMAT,"epoch":i.config["epoch"],"order":header,"section":section,"items":items,"next_offset":if more{json!(next.to_string())}else{Value::Null}}),
    )
}
