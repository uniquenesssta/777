use crate::{auth, casefold, fail, protocol, Error, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use hmac::{Hmac, Mac};
use num_bigint::BigInt;
use quote_ledger::store::{self, Actor};
use rusqlite::{params_from_iter, types::Value as SqlValue, Connection};
use serde_json::{json, Value};
use sha2::Sha256;
use std::collections::{HashMap, VecDeque};
type Key = (Option<String>, Option<String>, String);
#[derive(Clone)]
struct Row {
    created_at: String,
    owner: String,
    state: String,
    search: String,
    money: [i64; 3],
}
fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Row> {
    let details: String = r.get(3)?;
    let id: String = r.get(0)?;
    Ok(Row {
        created_at: r.get(8)?,
        owner: r.get(1)?,
        state: r.get(2)?,
        search: search(&details, &id),
        money: [r.get(4)?, r.get(5)?, r.get(6)?],
    })
}
fn search(details: &str, id: &str) -> String {
    let d: Value = serde_json::from_str(details).unwrap_or(Value::Null);
    let mut a = d
        .as_object()
        .map(|o| {
            o.values()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    a.push(id.into());
    casefold(&a.join("\n"))
}
fn matches(r: &Row, k: &Key) -> bool {
    k.0.as_ref().is_none_or(|v| v == &r.owner)
        && k.1.as_ref().is_none_or(|v| v == &r.state)
        && (k.2.is_empty() || r.search.contains(&k.2))
}
const COLS: &str =
    "order_id,owner_id,state,details_json,income_cents,cost_cents,profit_cents,revision,created_at";
#[derive(Clone)]
struct Summary {
    key: Key,
    total: i64,
    money: [BigInt; 3],
}
pub struct Queries {
    secret: [u8; 32],
    revision: Option<i64>,
    rows: HashMap<String, Row>,
    summaries: VecDeque<Summary>,
    pub full_scans: usize,
    pub delta_rows: usize,
}
impl Queries {
    pub fn new() -> Result<Self> {
        Ok(Self {
            secret: auth::random()?,
            revision: None,
            rows: HashMap::new(),
            summaries: VecDeque::new(),
            full_scans: 0,
            delta_rows: 0,
        })
    }
    fn tag(&self, v: &Value) -> String {
        let mut m = Hmac::<Sha256>::new_from_slice(&self.secret).expect("fixed secret");
        m.update(store::encoded(v).as_bytes());
        format!("{:x}", m.finalize().into_bytes())
    }
    fn cursor(&self, v: &Value) -> String {
        format!(
            "{}.{}",
            URL_SAFE_NO_PAD.encode(store::encoded(v)),
            self.tag(v)
        )
    }
    fn decode(&self, s: &str) -> Result<Value> {
        if s.len() > 2048 {
            return fail(422, "INVALID_CURSOR");
        };
        let (raw, tag) = s
            .split_once('.')
            .ok_or_else(|| Error::new(422, "INVALID_CURSOR"))?;
        let raw = URL_SAFE_NO_PAD
            .decode(raw)
            .map_err(|_| Error::new(422, "INVALID_CURSOR"))?;
        let v = protocol::decode(&raw, 2048).map_err(|_| Error::new(422, "INVALID_CURSOR"))?;
        let expected = self.tag(&v);
        use subtle::ConstantTimeEq;
        if expected.as_bytes().ct_eq(tag.as_bytes()).unwrap_u8() != 1 {
            return fail(422, "INVALID_CURSOR");
        }
        protocol::fields(&v, &["format", "view", "binding", "after"], &[])
            .map_err(|_| Error::new(422, "INVALID_CURSOR"))?;
        if v["format"] != "777-query-v1"
            || v["after"]
                .as_array()
                .is_none_or(|a| a.len() != 2 || a.iter().any(|v| !v.is_string()))
        {
            return fail(422, "INVALID_CURSOR");
        }
        Ok(v)
    }
    fn change(&mut self, r: &Row, direction: i64) {
        for s in &mut self.summaries {
            if matches(r, &s.key) {
                s.total += direction;
                if r.state == "active" {
                    for (i, v) in r.money.iter().enumerate() {
                        s.money[i] += BigInt::from(*v) * direction;
                    }
                }
            }
        }
    }
    fn synchronize(&mut self, c: &Connection, revision: i64) -> Result<()> {
        if self.revision.is_none_or(|r| revision < r) {
            self.rows.clear();
            let mut st = c.prepare(&format!(
                "SELECT {COLS} FROM orders WHERE {}",
                quote_ledger::deletion::VISIBLE
            ))?;
            let data = st
                .query_map([], |r| Ok((r.get::<_, String>(0)?, row(r)?)))?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            self.rows.extend(data);
            self.summaries.clear();
            self.full_scans += 1;
        } else if self.revision != Some(revision) {
            let mut st=c.prepare("SELECT DISTINCT a.order_id FROM audit_events a JOIN requests r ON a.request_id=r.request_id WHERE r.ledger_revision>? AND r.ledger_revision<=? AND a.order_id IS NOT NULL")?;
            let ids = st
                .query_map([self.revision.unwrap(), revision], |r| {
                    r.get::<_, String>(0)
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            for id in ids {
                if let Some(old) = self.rows.get(&id).cloned() {
                    self.change(&old, -1)
                }
                if quote_ledger::deletion::deleted(c, &id)? {
                    self.rows.remove(&id);
                    self.delta_rows += 1;
                    continue;
                }
                let next = c.query_row(
                    &format!("SELECT {COLS} FROM orders WHERE order_id=?"),
                    [&id],
                    row,
                )?;
                self.change(&next, 1);
                self.rows.insert(id, next);
                self.delta_rows += 1;
            }
        }
        self.revision = Some(revision);
        Ok(())
    }
    fn summary(&mut self, key: &Key) -> Summary {
        if let Some(i) = self.summaries.iter().position(|s| &s.key == key) {
            let s = self.summaries.remove(i).unwrap();
            self.summaries.push_back(s.clone());
            return s;
        }
        let mut s = Summary {
            key: key.clone(),
            total: 0,
            money: std::array::from_fn(|_| BigInt::from(0)),
        };
        for r in self.rows.values() {
            if matches(r, key) {
                s.total += 1;
                if r.state == "active" {
                    for i in 0..3 {
                        s.money[i] += r.money[i];
                    }
                }
            }
        }
        self.summaries.push_back(s.clone());
        if self.summaries.len() > 32 {
            self.summaries.pop_front();
        }
        s
    }
    pub fn analytics(&mut self, path: &std::path::Path, a: &Actor, query: &str) -> Result<Value> {
        auth::Auth::admin(a)?;
        let c = store::open(path, false)?;
        c.execute_batch("BEGIN")?;
        let revision = crate::number(&store::verify(&c)?["revision"])?;
        self.synchronize(&c, revision)?;
        crate::analytics::summarize(
            query,
            self.rows
                .values()
                .filter(|r| r.state == "active")
                .map(|r| (r.created_at.as_str(), r.money)),
            revision,
        )
    }
    pub fn listing(&mut self, path: &std::path::Path, a: &Actor, query: &str) -> Result<Value> {
        let mut p = HashMap::new();
        for (k, v) in form_urlencoded::parse(query.as_bytes()) {
            if !["offset", "limit", "state", "q", "cursor", "view", "format"].contains(&k.as_ref())
                || p.insert(k.into_owned(), v.into_owned()).is_some()
            {
                return fail(422, "INVALID_QUERY");
            }
        }
        let get = |k: &str| p.get(k).map(String::as_str);
        if get("format").is_some_and(|v| v != "777-query-v1") {
            return fail(409, "QUERY_VERSION_CONFLICT");
        }
        let integer = |k: &str, d: &str| -> Result<i64> { integer(get(k).unwrap_or(d)) };
        let offset = integer("offset", "0")?;
        let limit = integer("limit", "100")?;
        if !(0..=1000000).contains(&offset)
            || !(1..=200).contains(&limit)
            || get("state").is_some_and(|s| s != "active" && s != "void")
            || get("cursor").is_some_and(|s| !s.is_empty()) && offset != 0
        {
            return fail(422, "INVALID_QUERY");
        }
        let q = get("q").unwrap_or("");
        protocol::text(&json!(q), 256, false)?;
        let key = (
            if a.role != "admin" {
                Some(a.subject.clone())
            } else {
                None
            },
            get("state").map(str::to_string),
            casefold(q),
        );
        let binding = self.tag(&json!({"subject":a.subject,"role":a.role,"key":key,"limit":limit}));
        let c = store::open(path, false)?;
        c.execute_batch("BEGIN")?;
        let revision = crate::number(&store::verify(&c)?["revision"])?;
        self.synchronize(&c, revision)?;
        let view = self.tag(&json!({"revision":revision,"binding":binding}));
        let cursor = get("cursor")
            .filter(|v| !v.is_empty())
            .map(|v| self.decode(v))
            .transpose()?;
        if cursor
            .as_ref()
            .is_some_and(|v| v["binding"] != binding || v["view"] != view)
            || get("view").is_some_and(|v| !v.is_empty() && v != view)
        {
            return fail(409, "QUERY_VIEW_CHANGED");
        }
        let mut clauses = vec![quote_ledger::deletion::VISIBLE];
        let mut args: Vec<SqlValue> = vec![];
        if let Some(owner) = &key.0 {
            clauses.push("owner_id=?");
            args.push(owner.clone().into())
        }
        if let Some(state) = &key.1 {
            clauses.push("state=?");
            args.push(state.clone().into())
        }
        if !key.2.is_empty() {
            c.create_scalar_function(
                "search_text",
                2,
                rusqlite::functions::FunctionFlags::SQLITE_DETERMINISTIC,
                |ctx| Ok(search(&ctx.get::<String>(0)?, &ctx.get::<String>(1)?)),
            )?;
            clauses.push("instr(search_text(details_json,order_id),?)>0");
            args.push(key.2.clone().into())
        }
        if let Some(cur) = cursor {
            clauses.push("(created_at<? OR (created_at=? AND order_id<?))");
            args.push(cur["after"][0].as_str().unwrap().to_string().into());
            args.push(cur["after"][0].as_str().unwrap().to_string().into());
            args.push(cur["after"][1].as_str().unwrap().to_string().into());
        }
        let where_sql = if clauses.is_empty() {
            String::new()
        } else {
            format!(" WHERE {}", clauses.join(" AND "))
        };
        args.push((limit + 1).into());
        args.push(offset.into());
        let mut st=c.prepare(&format!("SELECT {COLS} FROM orders{where_sql} ORDER BY created_at DESC,order_id DESC LIMIT ? OFFSET ?"))?;
        let mut rows=st.query_map(params_from_iter(args),|r|{let mut v=json!({"order_id":r.get::<_,String>(0)?,"revision":r.get::<_,i64>(7)?,"state":r.get::<_,String>(2)?,"created_at":r.get::<_,String>(8)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(3)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(4)?.to_string()});if a.role=="admin"{v["owner_id"]=json!(r.get::<_,String>(1)?);v["cost_cents"]=json!(r.get::<_,i64>(5)?.to_string());v["profit_cents"]=json!(r.get::<_,i64>(6)?.to_string());}Ok(v)})?.collect::<std::result::Result<Vec<_>,_>>()?;
        let extra = rows.len() > limit as usize;
        rows.truncate(limit as usize);
        let next = if extra {
            let last = rows.last().unwrap();
            Some(self.cursor(&json!({"format":"777-query-v1","view":view,"binding":binding,"after":[last["created_at"],last["order_id"]]})))
        } else {
            None
        };
        let s = self.summary(&key);
        let mut v = json!({"orders":rows,"offset":offset,"limit":limit,"total":s.total,"totals":protocol::financial(json!({"income_cents":s.money[0].to_string(),"cost_cents":s.money[1].to_string(),"profit_cents":s.money[2].to_string()}),a),"format":"777-query-v1","view":view,"next_cursor":next});
        if a.role == "admin" {
            v["ledger_revision"] = json!(revision)
        }
        Ok(v)
    }
}
fn integer(raw: &str) -> Result<i64> {
    let s = raw.trim();
    let normalized = s
        .chars()
        .map(|c| quote_core::numbers::decimal_digit(c).map_or(c, |d| char::from(b'0' + d)))
        .collect::<String>();
    let b = normalized.as_bytes();
    for (i, c) in b.iter().enumerate() {
        if *c == b'_'
            && (i == 0
                || i + 1 == b.len()
                || !b[i - 1].is_ascii_digit()
                || !b[i + 1].is_ascii_digit())
        {
            return fail(422, "INVALID_QUERY");
        }
    }
    normalized
        .replace('_', "")
        .parse()
        .map_err(|_| Error::new(422, "INVALID_QUERY"))
}
