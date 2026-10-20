use crate::Result;
use rusqlite::{params, Connection};
use serde_json::{json, Value};
pub(super) fn list(c: &Connection, query: &str, offset: i64) -> Result<Value> {
    let tx = c.unchecked_transaction()?;
    let filter="a.operation='delete_order' AND (?1='' OR instr(o.details_json,?1)>0 OR instr(o.order_id,?1)>0)";
    let total: i64 = tx.query_row(
        &format!(
            "SELECT count(*) FROM audit_events a JOIN orders o USING(order_id) WHERE {filter}"
        ),
        [query],
        |r| r.get(0),
    )?;
    let mut st=tx.prepare(&format!("SELECT o.order_id,o.revision,o.details_json,o.income_cents,a.actor_id,a.created_at,json_extract(a.after_json,'$.reason') FROM audit_events a JOIN orders o USING(order_id) WHERE {filter} ORDER BY a.created_at DESC,a.event_id DESC LIMIT 20 OFFSET ?2"))?;
    let rows=st.query_map(params![query,offset],|r|Ok(json!({"order_id":r.get::<_,String>(0)?,"revision":r.get::<_,i64>(1)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(2)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(3)?.to_string(),"deleted_by":r.get::<_,String>(4)?,"deleted_at":r.get::<_,String>(5)?,"reason":r.get::<_,String>(6)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
    Ok(json!({"orders":rows,"total":total,"offset":offset,"limit":20}))
}
