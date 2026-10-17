//! Read-on-demand comparisons. Positions are explicit; regenerated line IDs are
//! never used to infer that two historical rows represent the same item.
use crate::{fail, Error, Result};
use quote_ledger::{editing, store::Actor};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{json, Value};

pub fn read(c: &Connection, actor: &Actor, id: &str, revision: i64) -> Result<Value> {
    let current = editing::owned(c, actor, id)?;
    let row: Option<(String, String)> = c
        .query_row(
            "SELECT snapshot_json,created_at FROM order_versions WHERE order_id=? AND revision=?",
            rusqlite::params![id, revision],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let Some((raw, at)) = row else {
        return fail(404, "NOT_FOUND");
    };
    let before = editing::validate_archive(c, id, revision, &raw)?;
    // Notes/state changes increment revisions but do not change saved line values.
    // The next pre-edit snapshot therefore contains this edit's resulting values.
    let next: Option<(i64, String)> = c.query_row(
        "SELECT revision,snapshot_json FROM order_versions WHERE order_id=? AND revision>? ORDER BY revision LIMIT 1",
        rusqlite::params![id, revision], |r| Ok((r.get(0)?, r.get(1)?)),
    ).optional()?;
    let after = match next {
        Some((rev, raw)) => editing::validate_archive(c, id, rev, &raw)?,
        None => current,
    };
    Ok(
        json!({"revision":revision.to_string(),"to_revision":(revision+1).to_string(),"created_at":at,"changes":compare(&before,&after,actor.role=="admin")?}),
    )
}
fn parsed(v: &Value, key: &str) -> Result<Value> {
    Ok(serde_json::from_str(
        v[key]
            .as_str()
            .ok_or_else(|| Error::new(503, "INVALID_DATABASE"))?,
    )?)
}
fn display(v: &Value) -> Value {
    if v.is_null() {
        Value::Null
    } else if let Some(s) = v.as_str() {
        json!(s)
    } else {
        json!(v.to_string())
    }
}
fn add(
    out: &mut Vec<Value>,
    section: &str,
    field: &str,
    before: &Value,
    after: &Value,
    format: &str,
) {
    let (before, after) = (display(before), display(after));
    if before != after {
        out.push(
            json!({"section":section,"field":field,"before":before,"after":after,"format":format}),
        );
    }
}
fn compare(before: &Value, after: &Value, admin: bool) -> Result<Vec<Value>> {
    let mut out = vec![];
    let bd = parsed(&before["order"], "details_json")?;
    let ad = parsed(&after["order"], "details_json")?;
    for (key, label) in [
        ("customer", "客户 / 淘宝 ID"),
        ("order_ref", "订单号"),
        ("wechat", "微信号"),
    ] {
        add(&mut out, "订单", label, &bd[key], &ad[key], "text");
    }
    let bl = before["lines"]
        .as_array()
        .ok_or_else(|| Error::new(503, "INVALID_DATABASE"))?;
    let al = after["lines"]
        .as_array()
        .ok_or_else(|| Error::new(503, "INVALID_DATABASE"))?;
    for i in 0..bl.len().max(al.len()) {
        let (b, a) = (bl.get(i), al.get(i));
        let section = format!(
            "第 {} 项{}",
            i + 1,
            if b.is_none() {
                "（新增）"
            } else if a.is_none() {
                "（删除）"
            } else {
                ""
            }
        );
        for (source, keys) in [
            (
                "raw_json",
                vec![
                    ("product_id", "商品"),
                    ("name", "名称"),
                    ("percent", "顺序折扣（%）"),
                ],
            ),
            (
                "normalized_json",
                vec![
                    ("h", "高（m）"),
                    ("w", "宽（m）"),
                    ("q", "数量"),
                    ("sale", "销售单价（元）"),
                ],
            ),
        ] {
            let b = b
                .map(|v| parsed(v, source))
                .transpose()?
                .unwrap_or(Value::Null);
            let a = a
                .map(|v| parsed(v, source))
                .transpose()?
                .unwrap_or(Value::Null);
            for (key, label) in keys {
                add(&mut out, &section, label, &b[key], &a[key], "text");
            }
            if admin && source == "normalized_json" {
                add(&mut out, &section, "K", &b["k"], &a["k"], "text");
            }
        }
        for (key, label) in [
            ("income_cents", "金额"),
            ("cost_cents", "成本"),
            ("profit_cents", "利润"),
        ] {
            if key == "income_cents" || admin {
                add(
                    &mut out,
                    &section,
                    label,
                    b.map(|v| &v[key]).unwrap_or(&Value::Null),
                    a.map(|v| &v[key]).unwrap_or(&Value::Null),
                    "money",
                );
            }
        }
    }
    for (key, label) in [
        ("income_cents", "收入"),
        ("cost_cents", "成本"),
        ("profit_cents", "利润"),
    ] {
        if key == "income_cents" || admin {
            add(
                &mut out,
                "订单合计",
                label,
                &before["order"][key],
                &after["order"][key],
                "money",
            );
        }
    }
    Ok(out)
}
