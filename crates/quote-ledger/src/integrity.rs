use crate::{paths, store::*, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use num_bigint::BigInt;
use quote_core::models::{NUMERIC_PROFILE, RULE_VERSION};
use rusqlite::{types::Value as SqlValue, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::{fs::OpenOptions, path::Path, time::Duration};
pub const TABLES: [&str; 9] = [
    "customers",
    "order_versions",
    "orders",
    "lines",
    "notes",
    "price_versions",
    "import_batches",
    "audit_events",
    "requests",
];
pub fn rows(c: &Connection, table: &str) -> Result<Vec<Vec<Value>>> {
    if !TABLES.contains(&table) {
        return Err(Error::new("VALIDATION"));
    }
    if ["customers", "order_versions"].contains(&table) && verify(c)?["schema_version"] == 1 {
        return Ok(vec![]);
    }
    let mut stmt = c.prepare(&format!("SELECT * FROM {table}"))?;
    let count = stmt.column_count();
    let records = stmt
        .query_map([], |r| {
            let mut row = vec![];
            for i in 0..count {
                row.push(match r.get::<_, SqlValue>(i)? {
                    SqlValue::Null => Value::Null,
                    SqlValue::Integer(n) => json!(n),
                    SqlValue::Text(s) => json!(s),
                    _ => return Err(rusqlite::Error::InvalidQuery),
                });
            }
            Ok(row)
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(records)
}
pub fn inventory(c: &Connection) -> Result<Value> {
    let meta = verify(c)?;
    let check: String = c.query_row("PRAGMA quick_check", [], |r| r.get(0))?;
    if check != "ok"
        || c.prepare("PRAGMA foreign_key_check")?
            .query([])?
            .next()?
            .is_some()
    {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let mut counts = serde_json::Map::new();
    for table in TABLES {
        if ["customers", "order_versions"].contains(&table) && meta["schema_version"] == 1 {
            continue;
        }
        counts.insert(
            table.into(),
            json!(
                c.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))?
            ),
        );
    }
    if counts["requests"] != meta["revision"] || counts["audit_events"] != counts["requests"] {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let chain:i64=c.query_row("SELECT COUNT(*) FROM requests r JOIN audit_events a ON r.request_id=a.request_id AND r.actor_id=a.actor_id AND r.operation=a.operation AND r.result_json=a.after_json WHERE r.ledger_revision>=1 AND r.ledger_revision<=(SELECT revision FROM ledger_meta WHERE singleton=1)",[],|r|r.get(0))?;
    if json!(chain) != counts["requests"] {
        return Err(Error::new("INVALID_DATABASE"));
    }
    for row in rows(c, "price_versions")? {
        if row[3] != RULE_VERSION || row[4] != NUMERIC_PROFILE {
            return Err(Error::new("INVALID_DATABASE"));
        }
        load_prices(
            c,
            row[0]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
        )?;
    }
    let mut sums = [BigInt::from(0), BigInt::from(0), BigInt::from(0)];
    for order in rows(c, "orders")? {
        let s = |i: usize| {
            order[i]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))
        };
        let q = decode_quote(serde_json::from_str(s(5)?)?)?;
        let p = load_prices(c, s(2)?)?;
        let overrides = crate::editing::saved_prices(c, s(0)?, s(2)?)?;
        let result = quote_core::calculation::calculate_with_prices(&q, &p, overrides.as_deref());
        if result.status != "ok"
            || order[3] != RULE_VERSION
            || order[4] != NUMERIC_PROFILE
            || q.price_version_id != order[2]
            || encoded(&legacy_quote(&q)) != s(5)?
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
        let a = result.totals.as_ref().unwrap();
        if [order[7].as_i64(), order[8].as_i64(), order[9].as_i64()]
            != [Some(a.income()), Some(a.cost()), Some(a.profit())]
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
        let mut stmt=c.prepare("SELECT sequence,kind,raw_json,normalized_json,price_json,income_cents,cost_cents,profit_cents,subtotal_before_cents FROM lines WHERE order_id=? ORDER BY sequence")?;
        let saved = stmt
            .query_map([s(0)?], |r| {
                Ok(json!([
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    r.get::<_, i64>(5)?,
                    r.get::<_, i64>(6)?,
                    r.get::<_, i64>(7)?,
                    r.get::<_, i64>(8)?
                ]))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let lines = result.lines.as_ref().unwrap();
        if saved.len() != lines.len() {
            return Err(Error::new("INVALID_DATABASE"));
        }
        for (saved, l) in saved.iter().zip(lines) {
            let normalized = l
                .normalized
                .iter()
                .map(|(k, v)| (k.clone(), json!(v)))
                .collect::<serde_json::Map<_, _>>();
            let expected = json!([
                l.sequence,
                legacy_line(&l.raw)["line_kind"],
                encoded(&legacy_line(&l.raw)),
                encoded(&json!(normalized)),
                l.price
                    .as_ref()
                    .map(|p| encoded(&serde_json::to_value(p).unwrap())),
                l.amounts.income(),
                l.amounts.cost(),
                l.amounts.profit(),
                l.subtotal_before
            ]);
            if *saved != expected {
                return Err(Error::new("INVALID_DATABASE"));
            }
        }
        if order[10] == "active" {
            sums[0] += a.income();
            sums[1] += a.cost();
            sums[2] += a.profit();
        }
    }
    for archived in rows(c, "order_versions")? {
        crate::editing::validate_archive(
            c,
            archived[0]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
            archived[1]
                .as_i64()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
            archived[2]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
        )?;
    }
    for batch in rows(c, "import_batches")? {
        let map: Value = serde_json::from_str(
            batch[5]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
        )?;
        let report = batch[6]
            .as_str()
            .ok_or_else(|| Error::new("INVALID_DATABASE"))?;
        let bytes = STANDARD
            .decode(
                map["source_base64"]
                    .as_str()
                    .ok_or_else(|| Error::new("INVALID_DATABASE"))?,
            )
            .map_err(|_| Error::new("INVALID_DATABASE"))?;
        if batch[4] != "committed"
            || bytes.len() > 20971520
            || json!(bytes.len()) != map["source_bytes"]
            || json!(hash(bytes)) != batch[1]
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
        let receipt: String = c.query_row(
            "SELECT result_json FROM requests WHERE request_id=? AND operation='import_batch'",
            [batch[0]
                .as_str()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?],
            |r| r.get(0),
        )?;
        if receipt != report {
            return Err(Error::new("INVALID_DATABASE"));
        }
    }
    let mut result = json!({"ledger_id":meta["ledger_id"],"schema_version":meta["schema_version"],"schema_hash":meta["schema_hash"],"revision":meta["revision"],"counts":counts,"active_income_cents":sums[0].to_string(),"active_cost_cents":sums[1].to_string(),"active_profit_cents":sums[2].to_string()});
    if meta["schema_version"] == 3 {
        result["offline_intake"] = crate::intake::inventory(c)?;
    }
    Ok(result)
}
pub fn backup(source: &Path, target: &Path) -> Result<Value> {
    paths::local(target, false)?;
    paths::sidecars(target)?;
    let fd = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)
        .map_err(|_| Error::new("EXISTS"))?;
    let work = || -> Result<Value> {
        let origin = open(source, false)?;
        let mut dest = Connection::open(target)?;
        {
            let snapshot = rusqlite::backup::Backup::new(&origin, &mut dest)?;
            snapshot.run_to_completion(128, Duration::from_millis(10), None)?;
        }
        dest.execute_batch("PRAGMA journal_mode=DELETE")?;
        let checked = inventory(&dest)?;
        drop(dest);
        fd.sync_all().map_err(|_| Error::new("BACKUP_IO"))?;
        let restored = open(target, false)?;
        if inventory(&restored)? != checked {
            return Err(Error::new("INVALID_DATABASE"));
        }
        Ok(checked)
    };
    match work() {
        Ok(v) => Ok(v),
        Err(e) => {
            drop(fd);
            let _ = std::fs::remove_file(target);
            Err(e)
        }
    }
}
pub fn apply_import(
    c: &mut Connection,
    actor: &Actor,
    data: &Value,
    crash: Option<&str>,
) -> Result<Value> {
    actor.admin()?;
    let rid = data["request_id"]
        .as_str()
        .ok_or_else(|| Error::new("VALIDATION"))?;
    id(rid)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    if let Some(old) = tx
        .query_row(
            "SELECT result_json FROM requests WHERE request_id=? AND operation='import_batch'",
            [rid],
            |r| r.get::<_, String>(0),
        )
        .optional()?
    {
        if serde_json::from_str::<Value>(&old)? != data["result"] {
            return Err(Error::new("CONFLICT"));
        }
        return Ok(serde_json::from_str(&old)?);
    }
    let meta = verify(&tx)?;
    if meta["revision"] != data["expected_revision"] {
        return Err(Error::new("CONFLICT"));
    }
    let adds = data["rows"]
        .as_object()
        .ok_or_else(|| Error::new("VALIDATION"))?;
    if adds.len() != 7
        || TABLES
            .iter()
            .filter(|t| !["customers", "order_versions"].contains(t))
            .any(|t| !adds.contains_key(*t))
    {
        return Err(Error::new("VALIDATION"));
    }
    // This is a fixed-table import delta, not arbitrary SQL or an external API.
    for table in [
        "price_versions",
        "orders",
        "lines",
        "notes",
        "requests",
        "audit_events",
        "import_batches",
    ] {
        let rows = adds[table]
            .as_array()
            .ok_or_else(|| Error::new("VALIDATION"))?;
        if rows.len() > 100000 {
            return Err(Error::new("VALIDATION"));
        }
        let width = match table {
            "price_versions" | "requests" => 7,
            "orders" => 15,
            "lines" => 12,
            "notes" => 6,
            "audit_events" | "import_batches" => 8,
            _ => unreachable!(),
        };
        let sql = format!("INSERT INTO {table} VALUES({})", vec!["?"; width].join(","));
        for row in rows {
            let row = row
                .as_array()
                .filter(|r| r.len() == width)
                .ok_or_else(|| Error::new("VALIDATION"))?;
            let values = row
                .iter()
                .map(|v| match v {
                    Value::Null => Ok(SqlValue::Null),
                    Value::String(s) => Ok(SqlValue::Text(s.clone())),
                    Value::Number(n) => n
                        .as_i64()
                        .map(SqlValue::Integer)
                        .ok_or_else(|| Error::new("VALIDATION")),
                    _ => Err(Error::new("VALIDATION")),
                })
                .collect::<Result<Vec<_>>>()?;
            if table == "requests"
                && (row[1] != actor.subject
                    || !row[3].as_str().is_some_and(|op| {
                        [
                            "import_prices",
                            "import_order",
                            "import_note",
                            "import_batch",
                        ]
                        .contains(&op)
                    }))
            {
                return Err(Error::new("FORBIDDEN"));
            }
            tx.execute(&sql, rusqlite::params_from_iter(values))?;
            if table == "lines" {
                fault("import_line_inserted", crash);
            }
        }
    }
    let next = data["final_inventory"]["revision"]
        .as_i64()
        .ok_or_else(|| Error::new("VALIDATION"))?;
    if next < meta["revision"].as_i64().unwrap() {
        return Err(Error::new("VALIDATION"));
    }
    tx.execute(
        "UPDATE ledger_meta SET revision=? WHERE singleton=1",
        [next],
    )?;
    if inventory(&tx)? != data["final_inventory"] {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let receipt = query_request(&tx, rid, actor)?;
    if receipt != data["result"] {
        return Err(Error::new("INVALID_DATABASE"));
    }
    fault("import_before_commit", crash);
    tx.commit().map_err(|_| Error::new("COMMIT_UNKNOWN"))?;
    fault("import_after_commit", crash);
    Ok(receipt)
}
