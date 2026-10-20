//! Scoped customer grouping. A matching identifier suggests, never merges, identities.
use crate::{protocol, Error, Result};
use quote_ledger::store::{self, Actor};
use rusqlite::{named_params, Connection};
use serde_json::{json, Value};
pub fn listing(c: &Connection, a: &Actor, data: &Value) -> Result<Value> {
    protocol::fields(
        data,
        &["query", "offset"],
        &["group_id", "order_offset", "identity"],
    )?;
    let identity = if data["identity"].is_null() {
        None
    } else {
        let value: quote_core::customer_identity::CustomerIdentity =
            serde_json::from_value(data["identity"].clone())
                .map_err(|_| Error::new(422, "INVALID_QUERY"))?;
        if !value.valid() {
            return Err(Error::new(422, "INVALID_QUERY"));
        }
        Some(value)
    };
    let identity_only = i32::from(identity.is_some());
    let name = identity.as_ref().map_or("", |v| v.customer.trim());
    let wechat = identity.as_ref().map_or("", |v| v.wechat.trim());
    let q = protocol::text(&data["query"], 256, false)?.trim();
    let offset = crate::number(&data["offset"])?;
    let order_offset = if data["order_offset"].is_null() {
        0
    } else {
        crate::number(&data["order_offset"])?
    };
    if !(0..=1_000_000).contains(&offset) || !(0..=1_000_000).contains(&order_offset) {
        return Err(Error::new(422, "INVALID_QUERY"));
    }
    let group = data["group_id"].as_str().unwrap_or("");
    if !group.is_empty() {
        store::id(group)?;
    }
    let tx = c.unchecked_transaction()?;
    let filter="(?1='admin' OR owner_id=?2) AND (?3='' OR instr(details_json,?3)>0) AND (?4='' OR coalesce(customer_id,order_id)=?4) AND (?5=0 OR ((?6!='' AND trim(json_extract(details_json,'$.customer'))=?6) OR (?7!='' AND trim(json_extract(details_json,'$.wechat'))=?7)))";
    let count: i64 = tx.query_row(
        &format!(
            "SELECT count(DISTINCT coalesce(customer_id,order_id)) FROM orders WHERE {filter}"
        ),
        rusqlite::params![a.role, a.subject, q, group, identity_only, name, wechat],
        |r| r.get(0),
    )?;
    let mut st=tx.prepare(&format!("SELECT coalesce(customer_id,order_id) FROM orders WHERE {filter} GROUP BY coalesce(customer_id,order_id) ORDER BY max(created_at) DESC,coalesce(customer_id,order_id) LIMIT 20 OFFSET ?8"))?;
    let ids = st
        .query_map(
            rusqlite::params![
                a.role,
                a.subject,
                q,
                group,
                identity_only,
                name,
                wechat,
                offset
            ],
            |r| r.get::<_, String>(0),
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let mut groups = vec![];
    for id in ids {
        let filter = "coalesce(customer_id,order_id)=:id AND (:role='admin' OR owner_id=:owner)";
        let args = named_params! {":id":id,":role":a.role,":owner":a.subject};
        let mut sums = [0i128; 3];
        let mut total = 0;
        let mut active = 0;
        let mut all = tx.prepare(&format!(
            "SELECT state,income_cents,cost_cents,profit_cents FROM orders WHERE {filter}"
        ))?;
        let mut rows = all.query(args)?;
        while let Some(r) = rows.next()? {
            total += 1;
            if r.get::<_, String>(0)? == "active" {
                active += 1;
                for (i, s) in sums.iter_mut().enumerate() {
                    *s += i128::from(r.get::<_, i64>(i + 1)?);
                }
            }
        }
        let mut st=tx.prepare(&format!("SELECT order_id,customer_id,details_json,revision,state,created_at,income_cents,cost_cents,profit_cents FROM orders WHERE {filter} ORDER BY created_at DESC,order_id DESC LIMIT 20 OFFSET :offset"))?;
        let orders=st.query_map(named_params!{":id":id,":role":a.role,":owner":a.subject,":offset":order_offset},|r|Ok(json!({"order_id":r.get::<_,String>(0)?,"customer_id":r.get::<_,Option<String>>(1)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(2)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"revision":r.get::<_,i64>(3)?.to_string(),"state":r.get::<_,String>(4)?,"created_at":r.get::<_,String>(5)?,"income_cents":r.get::<_,i64>(6)?.to_string(),"cost_cents":r.get::<_,i64>(7)?.to_string(),"profit_cents":r.get::<_,i64>(8)?.to_string()})))?.map(|r|r.map(|v|protocol::financial(v,a))).collect::<std::result::Result<Vec<_>,_>>()?;
        let first:Value=tx.query_row(&format!("SELECT details_json FROM orders WHERE {filter} ORDER BY created_at DESC,order_id DESC LIMIT 1"),args,|r|serde_json::from_str(&r.get::<_,String>(0)?).map_err(|_|rusqlite::Error::InvalidQuery))?;
        let totals = protocol::financial(
            json!({"income_cents":sums[0].to_string(),"cost_cents":sums[1].to_string(),"profit_cents":sums[2].to_string()}),
            a,
        );
        groups.push(json!({"group_id":id,"details":first,"orders":orders,"total":total,"active_count":active,"totals":totals,"order_offset":order_offset}));
    }
    Ok(json!({"groups":groups,"total":count,"offset":offset,"limit":20}))
}
