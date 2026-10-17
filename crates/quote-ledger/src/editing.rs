//! Revisioned editing and explicit customer association; service provides the actor.
use crate::{store::*, Error, Result};
use quote_core::{
    calculation::calculate_with_prices,
    models::{Line, PriceItem, Quote, QuoteResult},
};
use rusqlite::{params, types::Value as Sql, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::HashSet;
fn invalid() -> Error {
    Error::new("VALIDATION")
}
pub fn object_rows(c: &Connection, sql: &str, key: &str) -> Result<Vec<Value>> {
    let mut st = c.prepare(sql)?;
    let cols = st
        .column_names()
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
    let records = st
        .query_map([key], |r| {
            let mut obj = serde_json::Map::new();
            for (i, name) in cols.iter().enumerate() {
                obj.insert(
                    name.clone(),
                    match r.get::<_, Sql>(i)? {
                        Sql::Null => Value::Null,
                        Sql::Integer(n) => json!(n),
                        Sql::Text(s) => json!(s),
                        _ => return Err(rusqlite::Error::InvalidQuery),
                    },
                );
            }
            Ok(Value::Object(obj))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(records)
}
pub fn snapshot(c: &Connection, oid: &str) -> Result<Value> {
    let order = object_rows(c, "SELECT * FROM orders WHERE order_id=?", oid)?
        .into_iter()
        .next()
        .ok_or_else(invalid)?;
    let lines = object_rows(
        c,
        "SELECT * FROM lines WHERE order_id=? ORDER BY sequence",
        oid,
    )?;
    Ok(json!({"order":order,"lines":lines}))
}
pub fn owned(c: &Connection, actor: &Actor, oid: &str) -> Result<Value> {
    let s = snapshot(c, oid)?;
    if actor.role != "admin" && s["order"]["owner_id"] != actor.subject {
        return Err(Error::new("FORBIDDEN"));
    }
    Ok(s)
}
pub fn saved_prices(
    c: &Connection,
    oid: &str,
    fallback: &str,
) -> Result<Option<Vec<Option<PriceItem>>>> {
    if verify(c)?["schema_version"] == 1 {
        return Ok(None);
    }
    let lines = object_rows(
        c,
        "SELECT * FROM lines WHERE order_id=? ORDER BY sequence",
        oid,
    )?;
    let mut out = vec![];
    for l in lines {
        let raw: Value = serde_json::from_str(l["raw_json"].as_str().ok_or_else(invalid)?)?;
        if raw["line_kind"] == "discount" {
            out.push(None);
            continue;
        }
        let p = load_prices(c, l["price_version_id"].as_str().unwrap_or(fallback))?;
        out.push(Some(
            p.items
                .into_iter()
                .find(|p| p.product_id == raw["product_id"])
                .ok_or_else(invalid)?,
        ));
    }
    Ok(Some(out))
}
pub fn preview(
    c: &Connection,
    actor: &Actor,
    oid: Option<&str>,
    revision: Option<i64>,
    q: &Quote,
    sources: &[Option<String>],
) -> Result<(QuoteResult, Vec<String>)> {
    if oid.is_some() != revision.is_some()
        || revision.is_some_and(|r| r < 1)
        || sources.len() != q.lines.len()
    {
        return Err(invalid());
    }
    let old = oid.map(|id| owned(c, actor, id)).transpose()?;
    if let Some(old) = &old {
        if old["order"]["state"] != "active" || old["order"]["revision"].as_i64() != revision {
            return Err(Error::new("CONFLICT"));
        }
    }
    let p = active_prices(c)?;
    if q.price_version_id != p.price_version_id {
        return Err(Error::new("CONFLICT"));
    }
    let active = p.price_version_id.as_str().ok_or_else(invalid)?;
    let mut prices = vec![];
    let mut ids = vec![];
    let mut seen = HashSet::new();
    for (raw, source) in q.lines.iter().zip(sources) {
        let mut pid = active.to_string();
        if let Some(source) = source {
            if !seen.insert(source) {
                return Err(invalid());
            }
            let old = old.as_ref().ok_or_else(invalid)?;
            let l = old["lines"]
                .as_array()
                .unwrap()
                .iter()
                .find(|l| l["line_id"] == *source)
                .ok_or_else(invalid)?;
            let prior: Value = serde_json::from_str(l["raw_json"].as_str().ok_or_else(invalid)?)?;
            if let Line::Normal { product_id, .. } = raw {
                if prior["product_id"] == *product_id {
                    pid = l["price_version_id"]
                        .as_str()
                        .unwrap_or(old["order"]["price_id"].as_str().ok_or_else(invalid)?)
                        .to_owned();
                }
            }
        }
        prices.push(if let Line::Normal { product_id, .. } = raw {
            Some(
                load_prices(c, &pid)?
                    .items
                    .into_iter()
                    .find(|p| p.product_id == *product_id)
                    .ok_or_else(invalid)?,
            )
        } else {
            None
        });
        ids.push(pid);
    }
    Ok((calculate_with_prices(q, &p, Some(&prices)), ids))
}
pub fn customer(
    c: &Connection,
    actor: &Actor,
    details: &Value,
    choice: &Value,
    oid: Option<&str>,
) -> Result<Option<String>> {
    let name = details["customer"].as_str().ok_or_else(invalid)?.trim();
    let wechat = details["wechat"].as_str().ok_or_else(invalid)?.trim();
    if name.is_empty() && wechat.is_empty() {
        return Ok(None);
    }
    let mut selected = choice["customer_id"].as_str().map(str::to_string);
    if let Some(anchor) = choice["anchor_order_id"].as_str() {
        id(anchor)?;
        let s = owned(c, actor, anchor)?;
        if let Some(cid) = s["order"]["customer_id"].as_str() {
            selected = Some(cid.into());
        } else {
            let d: Value =
                serde_json::from_str(s["order"]["details_json"].as_str().ok_or_else(invalid)?)?;
            if (!name.is_empty() && d["customer"] != name)
                || (!wechat.is_empty() && d["wechat"] != wechat)
            {
                return Err(Error::new("CUSTOMER_IDENTITY_CONFLICT"));
            }
            // Legacy order ID is its explicit group key. Linking another order
            // does not silently revise the anchor's financial record.
            let cid = anchor.to_string();
            c.execute(
                "INSERT INTO customers VALUES(?,?,?,?) ON CONFLICT(customer_id) DO NOTHING",
                params![cid, d["customer"].as_str(), d["wechat"].as_str(), now()],
            )?;
            selected = Some(cid);
        }
    }
    if selected.is_none() && choice["new_customer"] != true {
        if let Some(oid) = oid {
            let old = owned(c, actor, oid)?;
            selected = old["order"]["customer_id"].as_str().map(str::to_string);
            if selected.is_none()
                && c.query_row(
                    "SELECT EXISTS(SELECT 1 FROM customers WHERE customer_id=?)",
                    [oid],
                    |r| r.get::<_, bool>(0),
                )?
            {
                selected = Some(oid.into());
            }
        }
    }
    if let Some(cid) = selected {
        id(&cid)?;
        let row: Option<(String, String)> = c
            .query_row(
                "SELECT name,wechat FROM customers WHERE customer_id=?",
                [&cid],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let (a, b) = row.ok_or_else(invalid)?;
        if actor.role != "admin"
            && !c.query_row(
                "SELECT EXISTS(SELECT 1 FROM orders WHERE COALESCE(customer_id,order_id)=? AND owner_id=?)",
                params![cid, actor.subject],
                |r| r.get::<_, bool>(0),
            )?
        {
            return Err(Error::new("FORBIDDEN"));
        }
        if (!name.is_empty() && name != a) || (!wechat.is_empty() && wechat != b) {
            return Err(Error::new("CUSTOMER_IDENTITY_CONFLICT"));
        }
        return Ok(Some(cid));
    }
    if choice["new_customer"] != true {
        let matches:i64=c.query_row("SELECT count(*) FROM customers c WHERE ((?!='' AND c.name=?) OR (?!='' AND c.wechat=?)) AND (?='admin' OR EXISTS(SELECT 1 FROM orders o WHERE COALESCE(o.customer_id,o.order_id)=c.customer_id AND o.owner_id=?))",params![name,name,wechat,wechat,actor.role,actor.subject],|r|r.get(0))?;
        if matches > 0 {
            return Err(Error::new("CUSTOMER_SELECTION_REQUIRED"));
        }
    }
    let cid = uid()?;
    c.execute(
        "INSERT INTO customers VALUES(?,?,?,?)",
        params![cid, name, wechat, now()],
    )?;
    Ok(Some(cid))
}

/// Recompute an archived version from immutable published prices, then verify
/// every saved field used by reports. Corruption must fail closed on restore.
pub fn validate_archive(c: &Connection, oid: &str, revision: i64, raw: &str) -> Result<Value> {
    let s: Value = serde_json::from_str(raw)?;
    let o = &s["order"];
    let st = |key: &str| o[key].as_str().ok_or_else(invalid);
    if st("order_id")? != oid || o["revision"].as_i64() != Some(revision) || revision < 1 {
        return Err(invalid());
    }
    let current = snapshot(c, oid)?;
    for key in ["order_id", "owner_id", "created_at", "request_id"] {
        if o[key] != current["order"][key] {
            return Err(invalid());
        }
    }
    if current["order"]["revision"]
        .as_i64()
        .is_none_or(|v| v <= revision)
    {
        return Err(invalid());
    }
    let q = decode_quote(serde_json::from_str(st("input_json")?)?)?;
    let p = load_prices(c, st("price_id")?)?;
    if q.price_version_id != o["price_id"]
        || o["rule_version"] != quote_core::models::RULE_VERSION
        || o["numeric_profile"] != quote_core::models::NUMERIC_PROFILE
    {
        return Err(invalid());
    }
    let lines = s["lines"].as_array().ok_or_else(invalid)?;
    if lines.len() != q.lines.len() {
        return Err(invalid());
    }
    let mut prices = vec![];
    for (l, raw) in lines.iter().zip(&q.lines) {
        if l["order_id"] != oid {
            return Err(invalid());
        }
        prices.push(if let Line::Normal { product_id, .. } = raw {
            Some(
                load_prices(c, l["price_version_id"].as_str().unwrap_or(st("price_id")?))?
                    .items
                    .into_iter()
                    .find(|p| p.product_id == *product_id)
                    .ok_or_else(invalid)?,
            )
        } else {
            None
        });
    }
    let calculated = calculate_with_prices(&q, &p, Some(&prices));
    let total = calculated
        .totals
        .as_ref()
        .filter(|_| calculated.status == "ok")
        .ok_or_else(invalid)?;
    for (k, n) in [
        ("income_cents", total.income()),
        ("cost_cents", total.cost()),
        ("profit_cents", total.profit()),
    ] {
        if o[k].as_i64() != Some(n) {
            return Err(invalid());
        }
    }
    for (saved, l) in lines
        .iter()
        .zip(calculated.lines.as_ref().ok_or_else(invalid)?)
    {
        let expected = json!({"sequence":l.sequence,"kind":legacy_line(&l.raw)["line_kind"],"raw_json":encoded(&legacy_line(&l.raw)),"normalized_json":encoded(&serde_json::to_value(l.normalized.iter().cloned().collect::<std::collections::BTreeMap<_,_>>()).unwrap()),"price_json":l.price.as_ref().map(|p|encoded(&serde_json::to_value(p).unwrap())),"income_cents":l.amounts.income(),"cost_cents":l.amounts.cost(),"profit_cents":l.amounts.profit(),"subtotal_before_cents":l.subtotal_before});
        for (key, v) in expected.as_object().unwrap() {
            if saved[key] != *v {
                return Err(invalid());
            }
        }
    }
    let linked:bool=c.query_row("SELECT EXISTS(SELECT 1 FROM audit_events WHERE order_id=? AND operation='save_order' AND before_json=?)",params![oid,raw],|r|r.get(0))?;
    if !linked {
        return Err(invalid());
    }
    Ok(s)
}
