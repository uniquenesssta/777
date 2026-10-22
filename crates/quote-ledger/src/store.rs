use crate::{integrity, paths, Error, Result};
use quote_core::{
    calculation::calculate,
    configuration::{parse_config, Source},
    models::{Line, Prices, Quote, QuoteResult, NUMERIC_PROFILE, RULE_VERSION},
};
use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs::OpenOptions, path::Path, time::Duration};
pub const LEGACY_SCHEMA_HASH: &str =
    "96619d105269c85fa0d0354050ca97af0af290ba6485913867ed070962aff003";
pub const SCHEMA_HASH: &str = "1e36e82360f009d6301e0a1f0aec55a43eb43b67050be5084c940eb0c7d7ee71";
pub const MIGRATION: &str = include_str!("migrate.sql");
pub const DDL: &str = include_str!("../../../docs/verification/P05-01-schema.sql");
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Actor {
    pub subject: String,
    pub role: String,
}
impl Actor {
    pub fn check(&self) -> Result<()> {
        text(&self.subject, 256, true)?;
        if !["admin", "sales"].contains(&self.role.as_str()) {
            return Err(Error::new("FORBIDDEN"));
        }
        Ok(())
    }
    pub fn admin(&self) -> Result<()> {
        self.check()?;
        if self.role != "admin" {
            return Err(Error::new("FORBIDDEN"));
        }
        Ok(())
    }
}
pub fn encoded(v: &Value) -> String {
    serde_json::to_string(v).expect("JSON Value serializes")
}
pub fn hash(b: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(b.as_ref()))
}
pub fn id(s: &str) -> Result<()> {
    if s.len() != 36
        || !s.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
            }
        })
    {
        Err(Error::new("VALIDATION"))
    } else {
        Ok(())
    }
}
pub fn text(s: &str, limit: usize, required: bool) -> Result<()> {
    if s.chars().count() > limit
        || required && quote_core::numbers::trim(s).is_empty()
        || s.contains('\0')
    {
        Err(Error::new("VALIDATION"))
    } else {
        Ok(())
    }
}
pub fn uid() -> Result<String> {
    let mut b = [0u8; 16];
    getrandom::getrandom(&mut b).map_err(|_| Error::new("RANDOM_UNAVAILABLE"))?;
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    let s = b.iter().map(|b| format!("{b:02x}")).collect::<String>();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..]
    ))
}
pub fn now() -> String {
    let d = time::OffsetDateTime::now_utc();
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}+00:00",
        d.year(),
        d.month() as u8,
        d.day(),
        d.hour(),
        d.minute(),
        d.second(),
        d.microsecond()
    )
}
pub fn schema_hash(c: &Connection) -> Result<String> {
    let mut stmt=c.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")?;
    let rows = stmt
        .query_map([], |r| {
            Ok(json!([
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, Option<String>>(3)?
            ]))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(hash(encoded(&json!(rows))))
}
pub fn verify(c: &Connection) -> Result<Value> {
    let version: i64 = c.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    let app: i64 = c.query_row("PRAGMA application_id", [], |r| r.get(0))?;
    let expected = match version {
        1 => LEGACY_SCHEMA_HASH,
        2 => SCHEMA_HASH,
        3 => crate::intake::HASH,
        _ => return Err(Error::new("INVALID_DATABASE")),
    };
    if app != 0x3737374c || schema_hash(c)? != expected {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let meta=c.query_row("SELECT schema_version,schema_hash,ledger_id,revision,active_price_id FROM ledger_meta WHERE singleton=1",[],|r|Ok(json!({"schema_version":r.get::<_,i64>(0)?,"schema_hash":r.get::<_,String>(1)?,"ledger_id":r.get::<_,String>(2)?,"revision":r.get::<_,i64>(3)?,"active_price_id":r.get::<_,Option<String>>(4)?})))?;
    if meta["schema_version"] != version || meta["schema_hash"] != expected {
        return Err(Error::new("INVALID_DATABASE"));
    }
    Ok(meta)
}
/// Upgrade only a verified v1 ledger, atomically; unknown schemas are never rewritten.
pub fn migrate(c: &Connection) -> Result<()> {
    if verify(c)?["schema_version"]
        .as_i64()
        .is_some_and(|v| v >= 2)
    {
        return Ok(());
    }
    c.execute_batch("BEGIN IMMEDIATE")?;
    let result = (|| -> Result<()> {
        if verify(c)?["schema_version"]
            .as_i64()
            .is_some_and(|v| v >= 2)
        {
            c.execute_batch("COMMIT")?;
            return Ok(());
        }
        c.execute_batch(MIGRATION)?;
        if schema_hash(c)? != SCHEMA_HASH {
            return Err(Error::new("SCHEMA_SOURCE_MISMATCH"));
        }
        c.execute(
            "UPDATE ledger_meta SET schema_version=2,schema_hash=? WHERE singleton=1",
            [SCHEMA_HASH],
        )?;
        c.execute_batch("PRAGMA user_version=2")?;
        verify(c)?;
        c.execute_batch("COMMIT")?;
        Ok(())
    })();
    if result.is_err() {
        let _ = c.execute_batch("ROLLBACK");
    }
    result
}
pub fn open(path: &Path, write: bool) -> Result<Connection> {
    paths::local(path, true)?;
    paths::sidecars(path)?;
    let c = Connection::open_with_flags(
        path,
        if write {
            OpenFlags::SQLITE_OPEN_READ_WRITE
        } else {
            OpenFlags::SQLITE_OPEN_READ_ONLY
        },
    )?;
    c.busy_timeout(Duration::from_secs(3))?;
    c.execute_batch("PRAGMA foreign_keys=ON")?;
    verify(&c)?;
    if write {
        migrate(&c)?;
        let expected = paths::journal_mode(path);
        let mode: String =
            c.query_row(&format!("PRAGMA journal_mode={expected}"), [], |r| r.get(0))?;
        if !mode.eq_ignore_ascii_case(expected) {
            return Err(Error::new("INVALID_DATABASE"));
        }
        c.execute_batch("PRAGMA synchronous=FULL")?;
    } else {
        c.execute_batch("PRAGMA query_only=ON")?;
    }
    Ok(c)
}
pub fn create(path: &Path) -> Result<Value> {
    create_version(path, false)
}
pub fn create_version(path: &Path, legacy: bool) -> Result<Value> {
    paths::local(path, false)?;
    paths::sidecars(path)?;
    for suffix in ["-wal", "-shm"] {
        let mut n = path.as_os_str().to_os_string();
        n.push(suffix);
        if Path::new(&n).exists() {
            return Err(Error::new("EXISTS"));
        }
    }
    let owned = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| Error::new("EXISTS"))?;
    drop(owned);
    let make = || -> Result<Value> {
        let c = Connection::open(path)?;
        c.execute_batch(&format!(
            "PRAGMA foreign_keys=ON;PRAGMA journal_mode={};PRAGMA synchronous=FULL;BEGIN IMMEDIATE",
            paths::journal_mode(path)
        ))?;
        c.execute_batch(DDL)?;
        if !legacy {
            c.execute_batch(MIGRATION)?;
        }
        let hash = if legacy {
            LEGACY_SCHEMA_HASH
        } else {
            SCHEMA_HASH
        };
        let version = if legacy { 1 } else { 2 };
        if schema_hash(&c)? != hash {
            return Err(Error::new("SCHEMA_SOURCE_MISMATCH"));
        }
        c.execute(
            "INSERT INTO ledger_meta VALUES(1,?,?,?,0,NULL)",
            params![version, hash, uid()?],
        )?;
        c.execute_batch(&format!(
            "PRAGMA application_id=926365516;PRAGMA user_version={version};COMMIT"
        ))?;
        integrity::inventory(&c)
    };
    match make() {
        Ok(v) => Ok(v),
        Err(e) => {
            let _ = std::fs::remove_file(path);
            for suffix in ["-wal", "-shm"] {
                let mut n = path.as_os_str().to_os_string();
                n.push(suffix);
                let _ = std::fs::remove_file(Path::new(&n));
            }
            Err(e)
        }
    }
}
pub fn legacy_line(l: &Line) -> Value {
    let mut v = serde_json::to_value(l).unwrap();
    let o = v.as_object_mut().unwrap();
    let kind = o.remove("kind").unwrap();
    o.insert("line_kind".into(), kind);
    v
}
pub fn legacy_quote(q: &Quote) -> Value {
    let mut v = json!({"price_version_id":q.price_version_id,"rule_version":q.rule_version,"numeric_profile":q.numeric_profile,"lines":q.lines.iter().map(legacy_line).collect::<Vec<_>>()});
    if let Some(price) = &q.final_price {
        v["final_price"] = json!(price);
    }
    v
}
pub fn decode_quote(mut v: Value) -> Result<Quote> {
    if let Some(ls) = v["lines"].as_array_mut() {
        for l in ls {
            let o = l
                .as_object_mut()
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?;
            let k = o
                .remove("line_kind")
                .ok_or_else(|| Error::new("INVALID_DATABASE"))?;
            o.insert("kind".into(), k);
        }
    }
    Ok(serde_json::from_value(v)?)
}
pub fn load_prices(c: &Connection, price_id: &str) -> Result<Prices> {
    let (raw, sha): (String, String) = c.query_row(
        "SELECT payload_json,payload_sha256 FROM price_versions WHERE price_id=?",
        [price_id],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    if hash(&raw) != sha {
        return Err(Error::new("INVALID_DATABASE"));
    }
    parse_config(Source::Text(&raw), &json!(price_id), None)
        .config
        .map(|c| c.prices)
        .ok_or_else(|| Error::new("INVALID_DATABASE"))
}
pub fn active_prices(c: &Connection) -> Result<Prices> {
    let meta = verify(c)?;
    let id = meta["active_price_id"]
        .as_str()
        .ok_or_else(|| Error::new("PRICES_NOT_PUBLISHED"))?;
    load_prices(c, id)
}
pub fn query_request(c: &Connection, rid: &str, actor: &Actor) -> Result<Value> {
    id(rid)?;
    actor.check()?;
    let row: Option<(String, String)> = c
        .query_row(
            "SELECT actor_id,result_json FROM requests WHERE request_id=?",
            [rid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    match row {
        None => Ok(Value::Null),
        Some((owner, raw)) => {
            if actor.role != "admin" && owner != actor.subject {
                return Err(Error::new("FORBIDDEN"));
            }
            Ok(serde_json::from_str(&raw)?)
        }
    }
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Mutation {
    PublishPrices {
        request_id: String,
        actor: Actor,
        prices: Prices,
        expected_price_version_id: Option<String>,
    },
    SubmitOrder {
        request_id: String,
        actor: Actor,
        snapshot: Quote,
        details: Value,
    },
    SaveOrder {
        request_id: String,
        actor: Actor,
        order_id: Option<String>,
        expected_revision: Option<i64>,
        snapshot: Quote,
        details: Value,
        sources: Vec<Option<String>>,
        customer: Value,
    },
    AppendNote {
        request_id: String,
        actor: Actor,
        order_id: String,
        body: String,
        expected_revision: i64,
    },
    SetState {
        request_id: String,
        actor: Actor,
        order_id: String,
        state: String,
        reason: String,
        expected_revision: i64,
    },
}
pub fn fault(phase: &str, configured: Option<&str>) {
    if configured == Some(phase) {
        std::process::exit(if phase == "after_commit" { 18 } else { 17 });
    }
}
pub fn mutate(c: &mut Connection, m: Mutation, crash: Option<&str>) -> Result<Value> {
    let (rid, actor, operation, payload) = match &m {
        Mutation::PublishPrices {
            request_id,
            actor,
            prices,
            expected_price_version_id,
        } => {
            actor.admin()?;
            let id = prices
                .price_version_id
                .as_str()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            text(id, 256, true)?;
            if let Some(id) = expected_price_version_id {
                text(id, 256, true)?;
            }
            let items = prices
                .items
                .iter()
                .map(|p| {
                    let mut value = serde_json::to_value(p).unwrap();
                    let object = value.as_object_mut().unwrap();
                    let name = object.remove("product_id").unwrap();
                    object.insert("name".into(), name);
                    value
                })
                .collect::<Vec<_>>();
            let raw = encoded(&json!({"items":items}));
            let parsed = parse_config(Source::Text(&raw), &prices.price_version_id, None)
                .config
                .ok_or_else(|| Error::new("VALIDATION"))?;
            let items = items
                .into_iter()
                .zip(parsed.prices.items)
                .map(|(mut value, p)| {
                    if p.pricing_mode == Some(quote_core::models::PricingMode::CostPlus) {
                        value["sale"] = p.sale;
                    }
                    value
                })
                .collect::<Vec<_>>();
            (
                request_id,
                actor,
                "publish_prices",
                json!({"price_id":prices.price_version_id,"expected_price_version_id":expected_price_version_id,"items":items}),
            )
        }
        Mutation::SubmitOrder {
            request_id,
            actor,
            snapshot,
            details,
        } => {
            let d = details
                .as_object()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            if d.len() != 3
                || !["customer", "order_ref", "wechat"]
                    .iter()
                    .all(|k| d.contains_key(*k))
            {
                return Err(Error::new("VALIDATION"));
            }
            for v in d.values() {
                text(
                    v.as_str().ok_or_else(|| Error::new("VALIDATION"))?,
                    256,
                    false,
                )?;
            }
            (
                request_id,
                actor,
                "submit_order",
                json!({"snapshot":legacy_quote(snapshot),"details":details}),
            )
        }
        Mutation::SaveOrder {
            request_id,
            actor,
            order_id,
            expected_revision,
            snapshot,
            details,
            sources,
            customer,
        } => {
            let d = details
                .as_object()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            if d.len() != 3
                || !["customer", "order_ref", "wechat"]
                    .iter()
                    .all(|k| d.contains_key(*k))
            {
                return Err(Error::new("VALIDATION"));
            }
            for v in d.values() {
                text(
                    v.as_str().ok_or_else(|| Error::new("VALIDATION"))?,
                    256,
                    false,
                )?;
            }
            if let Some(oid) = order_id {
                id(oid)?;
                if expected_revision.is_none_or(|r| r < 1) {
                    return Err(Error::new("VALIDATION"));
                }
            }
            if order_id.is_none() && expected_revision.is_some() {
                return Err(Error::new("VALIDATION"));
            }
            let choice = customer
                .as_object()
                .ok_or_else(|| Error::new("VALIDATION"))?;
            if choice.len() > 1
                || choice.iter().any(|(k, v)| match k.as_str() {
                    "new_customer" => v != true,
                    "customer_id" | "anchor_order_id" => v.as_str().is_none_or(|s| id(s).is_err()),
                    _ => true,
                })
            {
                return Err(Error::new("VALIDATION"));
            }
            if choice
                .keys()
                .any(|k| !["customer_id", "anchor_order_id", "new_customer"].contains(&k.as_str()))
            {
                return Err(Error::new("VALIDATION"));
            }
            (
                request_id,
                actor,
                "save_order",
                json!({"order_id":order_id,"expected_revision":expected_revision,"snapshot":legacy_quote(snapshot),"details":details,"sources":sources,"customer":customer}),
            )
        }
        Mutation::AppendNote {
            request_id,
            actor,
            order_id,
            body,
            expected_revision,
        } => {
            text(body, 4096, true)?;
            id(order_id)?;
            if *expected_revision < 1 {
                return Err(Error::new("VALIDATION"));
            }
            (
                request_id,
                actor,
                "append_note",
                json!({"order_id":order_id,"body":body,"expected_revision":expected_revision}),
            )
        }
        Mutation::SetState {
            request_id,
            actor,
            order_id,
            state,
            reason,
            expected_revision,
        } => {
            actor.admin()?;
            text(reason, 4096, true)?;
            id(order_id)?;
            if *expected_revision < 1 || !["active", "void"].contains(&state.as_str()) {
                return Err(Error::new("VALIDATION"));
            }
            (
                request_id,
                actor,
                "set_state",
                json!({"order_id":order_id,"state":state,"reason":reason,"expected_revision":expected_revision}),
            )
        }
    };
    id(rid)?;
    actor.check()?;
    let fingerprint = hash(encoded(
        &json!({"actor":actor,"operation":operation,"payload":payload}),
    ));
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let old: Option<(String, String)> = tx
        .query_row(
            "SELECT fingerprint,result_json FROM requests WHERE request_id=?",
            [rid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((old, raw)) = old {
        if old != fingerprint {
            return Err(Error::new("CONFLICT"));
        }
        return Ok(serde_json::from_str(&raw)?);
    }
    let meta = verify(&tx)?;
    let (result, order_id, before) = match &m {
        Mutation::PublishPrices {
            prices,
            expected_price_version_id,
            ..
        } => {
            if meta["active_price_id"] != json!(expected_price_version_id) {
                return Err(Error::new("CONFLICT"));
            }
            let key = prices.price_version_id.as_str().unwrap();
            if tx
                .query_row(
                    "SELECT 1 FROM price_versions WHERE price_id=?",
                    [key],
                    |r| r.get::<_, i64>(0),
                )
                .optional()?
                .is_some()
            {
                return Err(Error::new("CONFLICT"));
            }
            let raw = encoded(&json!({"items":payload["items"]}));
            tx.execute(
                "INSERT INTO price_versions VALUES(?,?,?,?,?,?,?)",
                params![
                    key,
                    raw,
                    hash(&raw),
                    RULE_VERSION,
                    NUMERIC_PROFILE,
                    actor.subject,
                    now()
                ],
            )?;
            tx.execute(
                "UPDATE ledger_meta SET active_price_id=? WHERE singleton=1",
                [key],
            )?;
            (json!({"price_version_id":key}), None, Value::Null)
        }
        Mutation::SubmitOrder {
            snapshot, details, ..
        } => {
            if snapshot.price_version_id != meta["active_price_id"] {
                return Err(Error::new("CONFLICT"));
            }
            let p = active_prices(&tx)?;
            let result = calculate(snapshot, &p);
            if result.status != "ok" {
                return Err(Error::new("VALIDATION"));
            }
            let oid = uid()?;
            let amount = result.totals.as_ref().unwrap();
            tx.execute(
                "INSERT INTO orders(order_id,owner_id,price_id,rule_version,numeric_profile,input_json,details_json,income_cents,cost_cents,profit_cents,state,revision,created_at,request_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                params![
                    oid,
                    actor.subject,
                    snapshot.price_version_id.as_str().unwrap(),
                    RULE_VERSION,
                    NUMERIC_PROFILE,
                    encoded(&legacy_quote(snapshot)),
                    encoded(details),
                    amount.income(),
                    amount.cost(),
                    amount.profit(),
                    "active",
                    1,
                    now(),
                    rid
                ],
            )?;
            insert_lines(&tx, &oid, &result, crash)?;
            (
                json!({"order_id":oid,"revision":1,"income_cents":amount.income().to_string(),"cost_cents":amount.cost().to_string(),"profit_cents":amount.profit().to_string()}),
                Some(oid),
                Value::Null,
            )
        }
        Mutation::SaveOrder {
            order_id,
            expected_revision,
            snapshot,
            details,
            sources,
            customer,
            ..
        } => {
            let (result, price_ids) = crate::editing::preview(
                &tx,
                actor,
                order_id.as_deref(),
                *expected_revision,
                snapshot,
                sources,
            )?;
            if result.status != "ok" {
                return Err(Error::new("VALIDATION"));
            }
            let before = order_id
                .as_ref()
                .map(|oid| crate::editing::owned(&tx, actor, oid))
                .transpose()?
                .unwrap_or(Value::Null);
            let cid = crate::editing::customer(&tx, actor, details, customer, order_id.as_deref())?;
            let order_ref = details["order_ref"].as_str().unwrap().trim();
            if let Some(cid) = &cid {
                if !order_ref.is_empty() && tx.query_row("SELECT EXISTS(SELECT 1 FROM orders WHERE NOT EXISTS(SELECT 1 FROM audit_events d WHERE d.order_id=orders.order_id AND d.operation='delete_order') AND COALESCE(customer_id,order_id)=? AND trim(json_extract(details_json,'$.order_ref'))=? AND order_id!=?)",params![cid,order_ref,order_id.as_deref().unwrap_or("")],|r|r.get::<_,bool>(0))?{return Err(Error::new("CUSTOMER_ORDER_NUMBER_EXISTS"));}
            }
            let oid = order_id.clone().map(Ok).unwrap_or_else(uid)?;
            let next = if let Some(rev) = expected_revision {
                rev.checked_add(1)
                    .ok_or_else(|| Error::new("REVISION_CAPACITY"))?
            } else {
                1
            };
            let amount = result.totals.as_ref().unwrap();
            if let Some(rev) = expected_revision {
                tx.execute(
                    "INSERT INTO order_versions VALUES(?,?,?,?,?)",
                    params![oid, rev, encoded(&before), actor.subject, now()],
                )?;
                tx.execute("UPDATE orders SET price_id=?,input_json=?,details_json=?,income_cents=?,cost_cents=?,profit_cents=?,revision=?,customer_id=? WHERE order_id=?",params![snapshot.price_version_id.as_str(),encoded(&legacy_quote(snapshot)),encoded(details),amount.income(),amount.cost(),amount.profit(),next,cid,oid])?;
                tx.execute("DELETE FROM lines WHERE order_id=?", [&oid])?;
            } else {
                tx.execute("INSERT INTO orders(order_id,owner_id,price_id,rule_version,numeric_profile,input_json,details_json,income_cents,cost_cents,profit_cents,state,revision,created_at,request_id,customer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![oid,actor.subject,snapshot.price_version_id.as_str(),RULE_VERSION,NUMERIC_PROFILE,encoded(&legacy_quote(snapshot)),encoded(details),amount.income(),amount.cost(),amount.profit(),"active",next,now(),rid,cid])?;
            }
            insert_lines(&tx, &oid, &result, crash)?;
            for (i, pid) in price_ids.iter().enumerate() {
                tx.execute(
                    "UPDATE lines SET price_version_id=? WHERE order_id=? AND sequence=?",
                    params![pid, oid, (i + 1) as i64],
                )?;
                if let Some(source) = &sources[i] {
                    tx.execute(
                        "UPDATE lines SET line_id=? WHERE order_id=? AND sequence=?",
                        params![source, oid, (i + 1) as i64],
                    )?;
                }
            }
            (
                json!({"order_id":oid,"customer_id":cid,"revision":next,"income_cents":amount.income().to_string(),"cost_cents":amount.cost().to_string(),"profit_cents":amount.profit().to_string()}),
                Some(oid),
                before,
            )
        }
        Mutation::AppendNote {
            order_id,
            body,
            expected_revision,
            ..
        } => {
            let (_, revision) = owned(&tx, actor, order_id)?;
            if revision != *expected_revision {
                return Err(Error::new("CONFLICT"));
            }
            let next = revision
                .checked_add(1)
                .ok_or_else(|| Error::new("REVISION_CAPACITY"))?;
            let before = crate::editing::snapshot(&tx, order_id)?;
            crate::editing::archive(&tx, actor, &before)?;
            let nid = uid()?;
            tx.execute(
                "INSERT INTO notes VALUES(?,?,?,?,?,?)",
                params![nid, order_id, actor.subject, body, now(), rid],
            )?;
            tx.execute(
                "UPDATE orders SET revision=? WHERE order_id=?",
                params![next, order_id],
            )?;
            (
                json!({"order_id":order_id,"note_id":nid,"revision":next}),
                Some(order_id.clone()),
                before,
            )
        }
        Mutation::SetState {
            order_id,
            state,
            reason,
            expected_revision,
            ..
        } => {
            let (old, revision) = owned(&tx, actor, order_id)?;
            if revision != *expected_revision || old == *state {
                return Err(Error::new("CONFLICT"));
            }
            let next = revision
                .checked_add(1)
                .ok_or_else(|| Error::new("REVISION_CAPACITY"))?;
            let before = crate::editing::snapshot(&tx, order_id)?;
            crate::editing::archive(&tx, actor, &before)?;
            tx.execute(
                "UPDATE orders SET state=?,revision=? WHERE order_id=?",
                params![state, next, order_id],
            )?;
            (
                json!({"order_id":order_id,"state":state,"reason":reason,"revision":next}),
                Some(order_id.clone()),
                before,
            )
        }
    };
    let result = crate::journal::record(
        &tx,
        crate::journal::Change {
            request_id: rid,
            actor,
            operation,
            fingerprint: &fingerprint,
            result,
            order_id: order_id.as_deref(),
            before: &before,
        },
    )?;
    fault("before_commit", crash);
    tx.commit().map_err(|_| Error::new("COMMIT_UNKNOWN"))?;
    fault("after_commit", crash);
    Ok(result)
}
fn owned(c: &Connection, actor: &Actor, oid: &str) -> Result<(String, i64)> {
    crate::deletion::available(c, oid)?;
    let row: Option<(String, String, i64)> = c
        .query_row(
            "SELECT owner_id,state,revision FROM orders WHERE order_id=?",
            [oid],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let (owner, state, revision) = row.ok_or_else(|| Error::new("VALIDATION"))?;
    if actor.role != "admin" && owner != actor.subject {
        return Err(Error::new("FORBIDDEN"));
    }
    Ok((state, revision))
}
fn insert_lines(
    c: &Connection,
    oid: &str,
    result: &QuoteResult,
    crash: Option<&str>,
) -> Result<()> {
    for l in result.lines.as_ref().unwrap() {
        let normalized = l
            .normalized
            .iter()
            .map(|(k, v)| (k.clone(), json!(v)))
            .collect::<serde_json::Map<_, _>>();
        c.execute(
            "INSERT INTO lines(line_id,order_id,sequence,kind,raw_json,normalized_json,price_json,income_cents,cost_cents,profit_cents,subtotal_before_cents) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            params![
                uid()?,
                oid,
                l.sequence as i64,
                match l.raw {
                    Line::Normal { .. } => "normal",
                    Line::Discount { .. } => "discount",
                },
                encoded(&legacy_line(&l.raw)),
                encoded(&json!(normalized)),
                l.price
                    .as_ref()
                    .map(|p| encoded(&serde_json::to_value(p).unwrap())),
                l.amounts.income(),
                l.amounts.cost(),
                l.amounts.profit(),
                l.subtotal_before
            ],
        )?;
        fault("line_inserted", crash);
    }
    Ok(())
}
