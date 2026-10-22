use super::Order;
use crate::{editing, journal, store::*, Error, Result};
use quote_core::{calculation::calculate_with_prices, models::Line};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
/// Caller owns the transaction, including the intake state and conflict decision.
pub struct Change<'a> {
    pub actor: &'a Actor,
    pub request: &'a str,
    pub fingerprint: &'a str,
    pub kind: &'a str,
    pub order: &'a Order,
    pub payload: &'a Value,
    pub customer: &'a Value,
}
pub fn apply(c: &Connection, change: Change<'_>) -> Result<Value> {
    let Change {
        actor,
        request,
        fingerprint,
        kind,
        order,
        payload,
        customer,
    } = change;
    if c.is_autocommit() {
        return Err(Error::new("TRANSACTION_REQUIRED"));
    }
    actor.check()?;
    id(request)?;
    id(&order.order_id)?;
    crate::deletion::available(c, &order.order_id)?;
    let old: Option<i64> = c
        .query_row(
            "SELECT revision FROM orders WHERE order_id=?",
            [&order.order_id],
            |r| r.get(0),
        )
        .optional()?;
    if old.unwrap_or(0) != order.revision {
        return Err(Error::new("CONFLICT"));
    }
    if actor.role != "admin" && actor.subject != order.owner_id {
        return Err(Error::new("FORBIDDEN"));
    }
    let before = if old.is_some() {
        editing::owned(c, actor, &order.order_id)?
    } else {
        Value::Null
    };
    let next = order
        .revision
        .checked_add(1)
        .ok_or_else(|| Error::new("REVISION_CAPACITY"))?;
    let operation = match kind {
        "create" | "edit" => "save_order",
        "append_note" => "append_note",
        "set_state" => "set_state",
        _ => return Err(Error::new("VALIDATION")),
    };
    let mut result = json!({"order_id":order.order_id,"revision":next});
    if kind == "create" || kind == "edit" {
        for key in ["customer", "order_ref", "wechat"] {
            text(
                order.details[key]
                    .as_str()
                    .ok_or_else(|| Error::new("VALIDATION"))?,
                256,
                false,
            )?;
        }
        let mut q = decode_quote(
            json!({"price_version_id":order.price_version_id,"rule_version":quote_core::models::RULE_VERSION,"numeric_profile":quote_core::models::NUMERIC_PROFILE,"lines":order.lines.iter().map(|l|l.raw.clone()).collect::<Vec<_>>()}),
        )?;
        q.final_price = order.final_price.clone();
        let prices = load_prices(c, &order.price_version_id)?;
        let mut frozen = Vec::new();
        let mut ids = std::collections::HashSet::new();
        for (saved, raw) in order.lines.iter().zip(&q.lines) {
            id(&saved.line_id)?;
            if !ids.insert(&saved.line_id)
                || c.query_row(
                    "SELECT EXISTS(SELECT 1 FROM lines WHERE line_id=? AND order_id!=?)",
                    params![saved.line_id, order.order_id],
                    |r| r.get::<_, bool>(0),
                )?
            {
                return Err(Error::new("CONFLICT"));
            }
            frozen.push(if let Line::Normal { product_id, .. } = raw {
                Some(
                    load_prices(c, &saved.price_version_id)?
                        .items
                        .into_iter()
                        .find(|p| p.product_id == *product_id)
                        .ok_or_else(|| Error::new("VALIDATION"))?,
                )
            } else {
                None
            });
        }
        let calculated = calculate_with_prices(&q, &prices, Some(&frozen));
        let amount = calculated
            .totals
            .as_ref()
            .filter(|_| calculated.status == "ok")
            .ok_or_else(|| Error::new("VALIDATION"))?;
        let cid = editing::customer(
            c,
            actor,
            &order.details,
            customer,
            old.map(|_| order.order_id.as_str()),
        )?;
        if old.is_some() {
            editing::archive(c, actor, &before)?;
            c.execute("UPDATE orders SET price_id=?,input_json=?,details_json=?,income_cents=?,cost_cents=?,profit_cents=?,revision=?,customer_id=? WHERE order_id=?",params![order.price_version_id,encoded(&legacy_quote(&q)),encoded(&order.details),amount.income(),amount.cost(),amount.profit(),next,cid,order.order_id])?;
            c.execute("DELETE FROM lines WHERE order_id=?", [&order.order_id])?;
        } else {
            c.execute("INSERT INTO orders(order_id,owner_id,price_id,rule_version,numeric_profile,input_json,details_json,income_cents,cost_cents,profit_cents,state,revision,created_at,request_id,customer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![order.order_id,order.owner_id,order.price_version_id,quote_core::models::RULE_VERSION,quote_core::models::NUMERIC_PROFILE,encoded(&legacy_quote(&q)),encoded(&order.details),amount.income(),amount.cost(),amount.profit(),"active",next,order.created_at,request,cid])?;
        }
        for (saved, line) in order.lines.iter().zip(calculated.lines.as_ref().unwrap()) {
            let normalized: std::collections::BTreeMap<_, _> =
                line.normalized.iter().cloned().collect();
            c.execute(
                "INSERT INTO lines VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                params![
                    saved.line_id,
                    order.order_id,
                    line.sequence as i64,
                    legacy_line(&line.raw)["line_kind"].as_str(),
                    encoded(&legacy_line(&line.raw)),
                    encoded(&json!(normalized)),
                    line.price
                        .as_ref()
                        .map(|p| encoded(&serde_json::to_value(p).unwrap())),
                    line.amounts.income(),
                    line.amounts.cost(),
                    line.amounts.profit(),
                    line.subtotal_before,
                    saved.price_version_id
                ],
            )?;
        }
        result["income_cents"] = json!(amount.income().to_string());
        result["cost_cents"] = json!(amount.cost().to_string());
        result["profit_cents"] = json!(amount.profit().to_string());
        result["customer_id"] = json!(cid);
    } else {
        if old.is_none() {
            return Err(Error::new("VALIDATION"));
        }
        editing::archive(c, actor, &before)?;
        if kind == "append_note" {
            let nid = payload["note_id"]
                .as_str()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            id(nid)?;
            let body = payload["body"]
                .as_str()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            text(body, 4096, true)?;
            c.execute(
                "INSERT INTO notes VALUES(?,?,?,?,?,?)",
                params![nid, order.order_id, actor.subject, body, now(), request],
            )?;
            result["note_id"] = json!(nid);
        } else {
            actor.admin()?;
            let reason = payload["reason"]
                .as_str()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            text(reason, 4096, true)?;
            if !["active", "void"].contains(&order.state.as_str()) {
                return Err(Error::new("VALIDATION"));
            }
            c.execute(
                "UPDATE orders SET state=? WHERE order_id=?",
                params![order.state, order.order_id],
            )?;
            result["state"] = json!(order.state);
            result["reason"] = json!(reason);
        }
        c.execute(
            "UPDATE orders SET revision=? WHERE order_id=?",
            params![next, order.order_id],
        )?;
    }
    journal::record(
        c,
        journal::Change {
            request_id: request,
            actor,
            operation,
            fingerprint,
            result,
            order_id: Some(&order.order_id),
            before: &before,
        },
    )
}
