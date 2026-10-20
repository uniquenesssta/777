use super::merge::conflict;
use crate::{Error, Result};
use quote_ledger::{
    application::{Line, Order},
    editing, store,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
pub(super) fn current(c: &Connection, id: &str) -> Result<Option<Order>> {
    let exists: bool = c.query_row(
        "SELECT EXISTS(SELECT 1 FROM orders WHERE order_id=?)",
        [id],
        |r| r.get(0),
    )?;
    if exists {
        Ok(Some(Order::read(c, id)?))
    } else {
        Ok(None)
    }
}
pub(super) fn basis(c: &Connection, v: &Value, current: &Order) -> Result<Order> {
    let rev = if let Some(previous) = v["base"]["previous_operation_id"].as_str() {
        let raw:Option<String>=c.query_row("SELECT r.result_json FROM offline_states s JOIN requests r ON r.request_id=s.applied_request_id WHERE s.operation_id=? AND s.state='applied'",[previous],|r|r.get(0)).optional()?;
        let result: Value =
            serde_json::from_str(&raw.ok_or_else(|| conflict("PREDECESSOR_NOT_APPLIED"))?)?;
        if result["order_id"] != v["order_id"] {
            return Err(conflict("DEPENDENCY_ORDER_CONFLICT"));
        }
        result["revision"]
            .as_i64()
            .ok_or_else(|| conflict("BASE_VERSION_UNAVAILABLE"))?
    } else {
        super::super::envelope::sequence(&v["base"]["order_revision"])?
    };
    if rev == current.revision {
        return Ok(current.clone());
    }
    let raw: Option<String> = c
        .query_row(
            "SELECT snapshot_json FROM order_versions WHERE order_id=? AND revision=?",
            params![current.order_id, rev],
            |r| r.get(0),
        )
        .optional()?;
    let raw = raw.ok_or_else(|| conflict("BASE_VERSION_UNAVAILABLE"))?;
    Ok(Order::from_snapshot(&editing::validate_archive(
        c,
        &current.order_id,
        rev,
        &raw,
    )?)?)
}
pub(super) fn propose(v: &Value, base: Option<&Order>, price: &str) -> Result<Order> {
    let p = &v["payload"];
    let kind = v["kind"].as_str().unwrap();
    if kind == "create" {
        return Ok(Order {
            order_id: v["order_id"].as_str().unwrap().into(),
            owner_id: v["owner_id"].as_str().unwrap().into(),
            revision: 0,
            price_version_id: p["snapshot"]["price_version_id"].as_str().unwrap().into(),
            created_at: v["created_at"].as_str().unwrap().into(),
            details: p["details"].clone(),
            lines: p["snapshot"]["lines"]
                .as_array()
                .unwrap()
                .iter()
                .map(|l| Line {
                    line_id: l["line_id"].as_str().unwrap().into(),
                    raw: l["raw"].clone(),
                    price_version_id: price.into(),
                })
                .collect(),
            state: "active".into(),
            customer_id: None,
        });
    }
    let mut next = base.ok_or_else(|| conflict("ORDER_NOT_FOUND"))?.clone();
    if next.owner_id != v["owner_id"] {
        return Err(Error::new(403, "FORBIDDEN"));
    }
    match kind {
        "edit" => {
            if next.state != "active" {
                return Err(conflict("ORDER_STATE_CONFLICT"));
            }
            for (k, value) in p["detail_changes"].as_object().unwrap() {
                next.details[k] = value.clone();
            }
            for change in p["line_changes"].as_array().unwrap() {
                let id = change["line_id"].as_str().unwrap();
                let pos = next.lines.iter().position(|l| l.line_id == id);
                match (change["op"].as_str().unwrap(), pos) {
                    ("add", None) => next.lines.push(Line {
                        line_id: id.into(),
                        raw: change["raw"].clone(),
                        price_version_id: price.into(),
                    }),
                    ("replace", Some(n)) => {
                        if next.lines[n].raw["product_id"] != change["raw"]["product_id"] {
                            next.lines[n].price_version_id = price.into();
                        }
                        next.lines[n].raw = change["raw"].clone();
                    }
                    ("remove", Some(n)) => {
                        next.lines.remove(n);
                    }
                    _ => return Err(conflict("LINE_ID_CONFLICT")),
                }
            }
        }
        "append_note" => {
            if next.state != "active" {
                return Err(conflict("ORDER_STATE_CONFLICT"));
            }
        }
        "set_state" => next.state = p["state"].as_str().unwrap().into(),
        _ => return Err(Error::new(422, "OFFLINE_KIND_INVALID")),
    }
    Ok(next)
}
pub(super) fn duplicate(c: &Connection, order: &Order) -> Result<Option<String>> {
    let reference = order.details["order_ref"].as_str().unwrap().trim();
    if reference.is_empty() {
        return Ok(None);
    }
    Ok(c.query_row("SELECT order_id FROM orders WHERE NOT EXISTS(SELECT 1 FROM audit_events d WHERE d.order_id=orders.order_id AND d.operation='delete_order') AND order_id!=? AND trim(json_extract(details_json,'$.order_ref'))=? ORDER BY order_id LIMIT 1",params![order.order_id,reference],|r|r.get(0)).optional()?)
}
pub(super) fn customer(
    c: &Connection,
    actor: &store::Actor,
    next: &Order,
    choice: &Value,
) -> Result<Value> {
    if choice.as_object().is_none_or(|o| !o.is_empty()) || next.revision != 0 {
        return Ok(choice.clone());
    }
    let name = next.details["customer"].as_str().unwrap().trim();
    let wechat = next.details["wechat"].as_str().unwrap().trim();
    let mut st=c.prepare("SELECT customer_id,name,wechat FROM customers c WHERE EXISTS(SELECT 1 FROM orders visible WHERE coalesce(visible.customer_id,visible.order_id)=c.customer_id AND NOT EXISTS(SELECT 1 FROM audit_events d WHERE d.order_id=visible.order_id AND d.operation='delete_order')) AND ((?!='' AND name=?) OR (?!='' AND wechat=?)) AND (?='admin' OR EXISTS(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.owner_id=?)) LIMIT 2")?;
    let rows = st
        .query_map(
            params![name, name, wechat, wechat, actor.role, actor.subject],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if rows.is_empty() {
        return Ok(choice.clone());
    }
    if rows.len() != 1
        || (!name.is_empty() && name != rows[0].1)
        || (!wechat.is_empty() && wechat != rows[0].2)
    {
        return Err(conflict("CUSTOMER_SELECTION_REQUIRED"));
    }
    Ok(json!({"customer_id":rows[0].0}))
}
