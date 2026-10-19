use crate::{
    auth::Auth,
    fail, files, image, number,
    protocol::{self, text},
    Error, Result,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::store::{self, encoded, hash, id, Actor};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};
pub const DDL: &str = include_str!("../../../docs/verification/P06-04-output-schema.sql");
const APP: i64 = 926365519;
const LIMIT: usize = 4 * 1024 * 1024;
const PROJECTION: &str =
    "job_id,order_id,kind,state,attempts,error,blob_sha256,size,created_at,payload_json";
pub struct Outputs {
    pub path: PathBuf,
    ledger_id: String,
}
#[derive(Clone)]
pub struct Job {
    pub id: String,
    pub actor: String,
    pub role: String,
    pub order: String,
    pub kind: String,
    pub payload: Value,
    pub payload_hash: String,
    pub blob_hash: Option<String>,
    pub size: Option<i64>,
}
fn job(r: &rusqlite::Row<'_>) -> rusqlite::Result<Job> {
    let raw: String = r.get("payload_json")?;
    Ok(Job {
        id: r.get("job_id")?,
        actor: r.get("actor_id")?,
        role: r.get("role")?,
        order: r.get("order_id")?,
        kind: r.get("kind")?,
        payload: serde_json::from_str(&raw).map_err(|_| rusqlite::Error::InvalidQuery)?,
        payload_hash: r.get("payload_sha256")?,
        blob_hash: r.get("blob_sha256")?,
        size: r.get("size")?,
    })
}
fn projection(r: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let payload: Value =
        serde_json::from_str(&r.get::<_, String>(9)?).map_err(|_| rusqlite::Error::InvalidQuery)?;
    Ok(
        json!({"batch":payload.get("batch"),"job_id":r.get::<_,String>(0)?,"order_id":r.get::<_,String>(1)?,"kind":r.get::<_,String>(2)?,"state":r.get::<_,String>(3)?,"attempts":r.get::<_,i64>(4)?,"error":r.get::<_,Option<String>>(5)?,"blob_sha256":r.get::<_,Option<String>>(6)?,"size":r.get::<_,Option<i64>>(7)?,"created_at":r.get::<_,String>(8)?,"range":payload["range"],"format":"777-output-v1"}),
    )
}
fn extension(kind: &str) -> Result<&'static str> {
    match kind {
        "excel_quote" | "excel_admin" | "excel_period" => Ok(".xlsx"),
        "quote_png" => Ok(".png"),
        _ => fail(422, "INVALID_OUTPUT_REQUEST"),
    }
}
pub fn public_order(mut v: Value) -> Value {
    v.as_object_mut().unwrap().retain(|k, _| {
        [
            "order_id",
            "revision",
            "state",
            "price_version_id",
            "created_at",
            "updated_at",
            "details",
            "income_cents",
            "notes",
            "rule_version",
            "numeric_profile",
            "lines",
        ]
        .contains(&k.as_str())
    });
    for l in v["lines"].as_array_mut().unwrap() {
        l.as_object_mut().unwrap().retain(|k, _| {
            [
                "sequence",
                "raw",
                "normalized",
                "subtotal_before_cents",
                "income_cents",
            ]
            .contains(&k.as_str())
        });
        protocol::normalized(
            &mut l["normalized"],
            &Actor {
                subject: "public".into(),
                role: "sales".into(),
            },
        );
    }
    v
}
impl Outputs {
    pub fn create(path: &Path, ledger_id: &str) -> Result<Self> {
        let folder = path.parent().unwrap().join("output-blobs");
        if folder.exists() {
            return fail(409, "EXISTS");
        }
        files::new_file(path, &[])?;
        let c = Connection::open(path)?;
        c.execute_batch(DDL)?;
        c.pragma_update(None, "application_id", APP)?;
        c.pragma_update(None, "user_version", 1)?;
        c.execute(
            "INSERT INTO meta VALUES(1,'777-output-store-v1',?)",
            [ledger_id],
        )?;
        drop(c);
        files::new_dir(&folder)?;
        Self::open(path.into(), ledger_id)
    }
    pub fn open(path: PathBuf, ledger_id: &str) -> Result<Self> {
        let s = Self {
            path,
            ledger_id: ledger_id.into(),
        };
        s.connection()?;
        Ok(s)
    }
    pub fn connection(&self) -> Result<Connection> {
        let c = files::database(&self.path, APP, DDL)?;
        let (format, id): (String, String) =
            c.query_row("SELECT format,ledger_id FROM meta WHERE id=1", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })?;
        if format != "777-output-store-v1" || id != self.ledger_id {
            return fail(503, "OUTPUT_STORE_INCOMPATIBLE");
        }
        Ok(c)
    }
    pub fn has_request(&self, key: &str) -> Result<bool> {
        Ok(self.connection()?.query_row(
            "SELECT EXISTS(SELECT 1 FROM receipts WHERE request_id=?)",
            [key],
            |r| r.get(0),
        )?)
    }
    pub fn receipt(&self, a: &Actor, key: &str, fp: Option<&str>) -> Result<Option<Value>> {
        id(key)?;
        let c = self.connection()?;
        let row: Option<(String, String, String)> = c
            .query_row(
                "SELECT actor_id,fingerprint,result_json FROM receipts WHERE request_id=?",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        if let Some((actor, fingerprint, raw)) = row {
            if a.role != "admin" && actor != a.subject {
                return fail(404, "NOT_FOUND");
            }
            if fp.is_some_and(|f| f != fingerprint) {
                return fail(409, "REVISION_OR_PRICE_CONFLICT");
            }
            let v: Value = serde_json::from_str(&raw)?;
            if a.role != "admin" {
                self.owned(
                    &c,
                    a,
                    v["job_id"]
                        .as_str()
                        .ok_or_else(|| Error::new(503, "OUTPUT_STORE_INCOMPATIBLE"))?,
                )?;
            }
            return Ok(Some(v));
        }
        Ok(None)
    }
    fn owned(&self, c: &Connection, a: &Actor, key: &str) -> Result<Job> {
        id(key)?;
        let j = c
            .query_row("SELECT * FROM jobs WHERE job_id=?", [key], job)
            .optional()?
            .ok_or_else(|| Error::new(404, "NOT_FOUND"))?;
        if a.role != "admin"
            && (j.actor != a.subject || matches!(j.kind.as_str(), "excel_admin" | "excel_period"))
        {
            return fail(404, "NOT_FOUND");
        }
        Ok(j)
    }
    pub fn enqueue(&self, a: &Actor, data: &Value, order: Value) -> Result<Value> {
        let key = text(&data["request_id"], 36, true)?;
        id(key)?;
        let mut fingerprint = data.clone();
        fingerprint["actor"] = json!(a.subject);
        fingerprint["role"] = json!(a.role);
        let fp = hash(encoded(&fingerprint));
        if let Some(v) = self.receipt(a, key, Some(&fp))? {
            return Ok(v);
        }
        let kind = text(&data["kind"], 32, true)?;
        extension(kind)?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        if tx.query_row(
            "SELECT count(*) FROM jobs WHERE state IN ('queued','running')",
            [],
            |r| r.get::<_, i64>(0),
        )? >= 64
        {
            return fail(429, "OUTPUT_QUEUE_FULL");
        }
        if matches!(kind, "excel_admin" | "excel_period") && a.role != "admin" {
            return fail(403, "FORBIDDEN");
        }
        let order = if matches!(kind, "excel_admin" | "excel_period") {
            order
        } else {
            public_order(order)
        };
        let payload = if kind == "excel_period" {
            json!({"format":"777-output-v1","presentation":"monthly-v1","generated_at":store::now(),"job_id":key,"kind":kind,"orders":order["orders"],"range":order["range"],"ledger_revision":order["ledger_revision"]})
        } else {
            json!({"format":"777-output-v1","presentation":"monthly-v1","generated_at":store::now(),"job_id":key,"kind":kind,"order":order})
        };
        let raw = encoded(&payload);
        if raw.len() > 2 * 1024 * 1024 {
            return fail(413, "OUTPUT_SNAPSHOT_TOO_LARGE");
        }
        tx.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,'queued',0,NULL,NULL,NULL,NULL,NULL,?)",
            params![
                key,
                a.subject,
                a.role,
                if kind == "excel_period" {
                    Some(key)
                } else {
                    order["order_id"].as_str()
                },
                kind,
                raw,
                hash(encoded(&payload)),
                store::now()
            ],
        )?;
        let receipt = json!({"request_id":key,"job_id":key,"order_id":order["order_id"],"order_revision":order["revision"],"kind":kind,"format":"777-output-v1","state":"queued"});
        tx.execute(
            "INSERT INTO receipts VALUES(?,?,?,?)",
            params![key, a.subject, fp, encoded(&receipt)],
        )?;
        tx.execute(
            "INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,'enqueue',?,?)",
            params![key, a.subject, store::now()],
        )?;
        tx.commit()?;
        Ok(receipt)
    }
    pub fn status(&self, a: &Actor, key: &str) -> Result<Value> {
        let c = self.connection()?;
        self.owned(&c, a, key)?;
        Ok(c.query_row(
            &format!("SELECT {PROJECTION} FROM jobs WHERE job_id=?"),
            [key],
            projection,
        )?)
    }
    pub fn location(&self, a: &Actor, key: &str) -> Result<Value> {
        let c = self.connection()?;
        self.owned(&c, a, key)?;
        let (state, path): (String, Option<String>) = c.query_row(
            "SELECT state,output_path FROM jobs WHERE job_id=?",
            [key],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        if state != "done" {
            return fail(409, "OUTPUT_NOT_READY");
        }
        let path = path.ok_or_else(|| Error::new(409, "OUTPUT_LOCATION_UNAVAILABLE"))?;
        Ok(json!({"output_path":path}))
    }
    pub fn listing(&self, a: &Actor) -> Result<Value> {
        self.listing_page(a, 0)
    }
    pub fn listing_page(&self, a: &Actor, offset: u32) -> Result<Value> {
        self.listing_page_scoped(a, offset, a.role == "admin")
    }
    pub fn listing_page_scoped(&self, a: &Actor, offset: u32, finance: bool) -> Result<Value> {
        let c = self.connection()?;
        let scope = if a.role == "admin" {
            if finance {
                "1=1"
            } else {
                "kind NOT IN ('excel_admin','excel_period')"
            }
        } else {
            "actor_id=?1 AND kind NOT IN ('excel_admin','excel_period')"
        };
        let params: Vec<&dyn rusqlite::ToSql> = if a.role == "admin" {
            vec![]
        } else {
            vec![&a.subject]
        };
        let total: i64 = c.query_row(
            &format!("SELECT count(*) FROM jobs WHERE {scope}"),
            params.as_slice(),
            |r| r.get(0),
        )?;
        let mut st=c.prepare(&format!("SELECT {PROJECTION} FROM jobs WHERE {scope} ORDER BY created_at DESC,order_id DESC,CAST(json_extract(payload_json,'$.batch.part') AS INTEGER),job_id DESC LIMIT 100 OFFSET {offset}"))?;
        let rows = st
            .query_map(params.as_slice(), projection)?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(json!({"jobs":rows,"limit":100,"offset":offset,"total":total,"format":"777-output-v1"}))
    }
    pub fn retry(&self, a: &Actor, key: &str, rid: &str) -> Result<Value> {
        id(rid)?;
        let fp = hash(encoded(
            &json!({"actor":a.subject,"job_id":key,"operation":"retry"}),
        ));
        if let Some(v) = self.receipt(a, rid, Some(&fp))? {
            return Ok(v);
        }
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        let j = self.owned(&tx, a, key)?;
        let state: String =
            tx.query_row("SELECT state FROM jobs WHERE job_id=?", [key], |r| r.get(0))?;
        if state == "running" {
            return fail(409, "OUTPUT_ALREADY_RUNNING");
        }
        if tx.query_row(
            "SELECT count(*) FROM jobs WHERE state IN ('queued','running')",
            [],
            |r| r.get::<_, i64>(0),
        )? >= 64
        {
            return fail(429, "OUTPUT_QUEUE_FULL");
        }
        tx.execute(
            "UPDATE jobs SET state='queued',error=NULL WHERE job_id=?",
            [key],
        )?;
        let v = json!({"request_id":rid,"job_id":key,"order_id":j.order,"state":"queued","format":"777-output-v1"});
        tx.execute(
            "INSERT INTO receipts VALUES(?,?,?,?)",
            params![rid, a.subject, fp, encoded(&v)],
        )?;
        tx.execute(
            "INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,'retry',?,?)",
            params![key, a.subject, store::now()],
        )?;
        tx.commit()?;
        Ok(v)
    }
    pub fn blob(&self, j: &Job) -> Result<Vec<u8>> {
        if hash(encoded(&j.payload)) != j.payload_hash {
            return fail(503, "OUTPUT_SNAPSHOT_CHANGED");
        }
        let raw = files::read(&self.blob_path(j)?, LIMIT)?;
        if j.blob_hash.as_ref().is_some_and(|sha| *sha != hash(&raw)) {
            return fail(503, "OUTPUT_BLOB_CHANGED");
        }
        validate(&raw, &j.payload)?;
        Ok(raw)
    }
    pub fn blob_path(&self, j: &Job) -> Result<PathBuf> {
        id(&j.id)?;
        let folder = self.path.parent().unwrap().join("output-blobs");
        files::dir(&folder)?;
        Ok(folder.join(j.id.clone() + extension(&j.kind)?))
    }
    pub fn content(&self, a: &Actor, key: &str) -> Result<Value> {
        let j = self.owned(&self.connection()?, a, key)?;
        if j.blob_hash.is_none() {
            return fail(409, "OUTPUT_NOT_RENDERED");
        }
        let raw = self.blob(&j)?;
        Ok(
            json!({"job_id":key,"format":"777-output-v1","filename":key.to_string()+extension(&j.kind)?,"size":raw.len(),"sha256":hash(&raw),"data_base64":STANDARD.encode(raw),"media_type":if j.kind=="quote_png"{"image/png"}else{"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}}),
        )
    }
    pub fn recover(&self) -> Result<()> {
        self.connection()?.execute(
            "UPDATE jobs SET state='queued',error='OUTPUT_RESTART_RECOVERY' WHERE state='running'",
            [],
        )?;
        Ok(())
    }
    pub fn prepare(&self, auth: &Auth, font: Option<PathBuf>) -> Result<Option<Work>> {
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        let j = tx
            .query_row(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created_at,job_id LIMIT 1",
                [],
                job,
            )
            .optional()?;
        let Some(j) = j else { return Ok(None) };
        tx.execute(
            "UPDATE jobs SET state='running',attempts=attempts+1,error=NULL WHERE job_id=?",
            [&j.id],
        )?;
        tx.commit()?;
        let user = auth
            .connection()?
            .query_row(
                "SELECT role,enabled FROM users WHERE id=?",
                [&j.actor],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)),
            )
            .optional()?;
        let error = if user.is_none_or(|u| u.0 != j.role || u.1 != 1) {
            Some("OUTPUT_ACCOUNT_CHANGED".to_string())
        } else {
            None
        };
        Ok(Some(Work {
            path: self.blob_path(&j)?,
            preferences: auth.preferences()?,
            job: j,
            font,
            error,
        }))
    }
    pub fn finish(&self, work: &Work, out: Outcome) -> Result<()> {
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        if let Some((sha, size)) = out.blob {
            tx.execute(
                "UPDATE jobs SET blob_sha256=?,size=? WHERE job_id=?",
                params![sha, size as i64, work.job.id],
            )?;
        }
        match out.target {
            Ok(path) => {
                tx.execute("UPDATE jobs SET state='done',error=NULL,output_path=?,settings_revision=? WHERE job_id=?",params![path.to_string_lossy(),number(&work.preferences["revision"])?,work.job.id])?;
                tx.execute(
                    "INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,'done',?,?)",
                    params![work.job.id, work.job.actor, store::now()],
                )?;
            }
            Err(e) => {
                tx.execute(
                    "UPDATE jobs SET state='failed',error=? WHERE job_id=?",
                    params![e.code, work.job.id],
                )?;
            }
        }
        tx.commit()?;
        Ok(())
    }
    pub fn backup(&self, target: &Path) -> Result<Vec<String>> {
        files::snapshot(&self.path, &target.join("outputs.sqlite3"), APP, DDL)?;
        let saved = Self::open(target.join("outputs.sqlite3"), &self.ledger_id)?;
        files::new_dir(&target.join("output-blobs"))?;
        let c = saved.connection()?;
        let mut st = c.prepare("SELECT * FROM jobs WHERE blob_sha256 IS NOT NULL")?;
        let jobs = st
            .query_map([], job)?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let mut names = vec!["outputs.sqlite3".into()];
        for j in jobs {
            let raw = self.blob(&j)?;
            let name = format!("output-blobs/{}{}", j.id, extension(&j.kind)?);
            files::new_file(&target.join(&name), &raw)?;
            names.push(name)
        }
        Ok(names)
    }
    pub fn validate_ledger(&self, path: &Path) -> Result<Vec<String>> {
        let c = self.connection()?;
        let l = store::open(path, false)?;
        self.validate_snapshot(&c, &l)
    }
    pub(crate) fn validate_snapshot(&self, c: &Connection, l: &Connection) -> Result<Vec<String>> {
        let mut st = c.prepare("SELECT * FROM jobs")?;
        let jobs = st
            .query_map([], job)?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let mut names = vec![];
        for j in jobs {
            if hash(encoded(&j.payload)) != j.payload_hash
                || j.payload["format"] != "777-output-v1"
                || j.payload["job_id"] != j.id
                || j.payload["kind"] != j.kind
            {
                return fail(503, "OUTPUT_LEDGER_BINDING_INVALID");
            }
            let admin = matches!(j.kind.as_str(), "excel_admin" | "excel_period");
            if admin && j.role != "admin" {
                return fail(503, "OUTPUT_LEDGER_BINDING_INVALID");
            }
            if j.kind == "excel_period" {
                for o in j.payload["orders"]
                    .as_array()
                    .ok_or_else(|| Error::new(503, "OUTPUT_LEDGER_BINDING_INVALID"))?
                {
                    validate_order_binding(l, o, admin)?;
                }
            } else {
                if j.payload["order"]["order_id"] != j.order {
                    return fail(503, "OUTPUT_LEDGER_BINDING_INVALID");
                }
                validate_order_binding(l, &j.payload["order"], admin)?;
            }
            if j.blob_hash.is_some() {
                self.blob(&j)?;
                names.push(format!("output-blobs/{}{}", j.id, extension(&j.kind)?));
            }
        }
        Ok(names)
    }
}
pub struct Work {
    pub job: Job,
    path: PathBuf,
    preferences: Value,
    font: Option<PathBuf>,
    error: Option<String>,
}
pub struct Outcome {
    blob: Option<(String, usize)>,
    target: Result<PathBuf>,
}
impl Work {
    pub fn execute(&self) -> Outcome {
        let mut blob = None;
        let target = (|| -> Result<PathBuf> {
            if let Some(e) = &self.error {
                return fail(403, e);
            }
            if hash(encoded(&self.job.payload)) != self.job.payload_hash {
                return fail(503, "OUTPUT_SNAPSHOT_CHANGED");
            }
            let raw = if self.path.exists() {
                let raw = files::read(&self.path, LIMIT)?;
                if self
                    .job
                    .blob_hash
                    .as_ref()
                    .is_some_and(|s| *s != hash(&raw))
                {
                    return fail(503, "OUTPUT_BLOB_CHANGED");
                }
                validate(&raw, &self.job.payload)?;
                raw
            } else {
                let raw = if self.job.kind == "quote_png" {
                    image::render(&self.job.payload, self.font.as_deref())?
                } else {
                    quote_excel::write::write(&self.job.payload)?
                };
                let tmp = self
                    .path
                    .with_extension(format!("{}.partial", store::uid()?));
                files::new_file(&tmp, &raw)?;
                let result = files::publish_new(&tmp, &self.path);
                let _ = fs::remove_file(&tmp);
                result?;
                raw
            };
            let sha = hash(&raw);
            blob = Some((sha.clone(), raw.len()));
            if matches!(self.job.kind.as_str(), "excel_admin" | "excel_period") {
                return Ok(self.path.clone());
            }
            let dir = self.preferences[if self.job.kind == "quote_png" {
                "image_dir"
            } else {
                "export_dir"
            }]
            .as_str()
            .ok_or_else(|| Error::new(409, "OUTPUT_DIRECTORY_NOT_PUBLISHED"))?;
            if dir.is_empty() {
                return fail(409, "OUTPUT_DIRECTORY_NOT_PUBLISHED");
            }
            publish(
                &self.path,
                Path::new(dir),
                &format!(
                    "777-{}-{}{}",
                    self.job.order,
                    self.job.id,
                    extension(&self.job.kind)?
                ),
                &sha,
            )
        })();
        Outcome { blob, target }
    }
}
pub fn validate(raw: &[u8], payload: &Value) -> Result<()> {
    if raw.is_empty() || raw.len() > LIMIT {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    if payload["kind"] == "quote_png" {
        return image::validate(raw, payload);
    }
    // Compare every read-back cell and style with the deterministic independent
    // format writer's matrix; old Python report XML/ZIP serialization may differ.
    let got = quote_excel::read::read(raw)?;
    let reference = quote_excel::read::read(&quote_excel::write::write(payload)?)?;
    let doc = serde_json::to_value(got)?;
    let expected = serde_json::to_value(reference)?;
    let same = |s: &Value| {
        let mut s = s.clone();
        s.as_object_mut().unwrap().remove("cells");
        s
    };
    if doc["sheets"].as_array().unwrap().len() != expected["sheets"].as_array().unwrap().len() {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    for (a, b) in doc["sheets"]
        .as_array()
        .unwrap()
        .iter()
        .zip(expected["sheets"].as_array().unwrap())
    {
        if same(a) != same(b) {
            return fail(422, "OUTPUT_BLOB_INVALID");
        }
        let cells = |s: &Value| -> Result<std::collections::BTreeMap<(i64, i64), Value>> {
            let mut m = std::collections::BTreeMap::new();
            for c in s["cells"].as_array().unwrap() {
                let text = c["value"].as_str().unwrap_or("");
                if !text.is_empty() && c["kind"] != "s" {
                    return fail(422, "OUTPUT_BLOB_INVALID");
                }
                let style = &doc["styles"][c["style"].as_u64().unwrap_or(0) as usize];
                if !text.is_empty()
                    && (style["num_fmt_id"] != 49 && style["format_code"] != "@"
                        || c["row"] == 1 && style["bold"] != true)
                {
                    return fail(422, "OUTPUT_BLOB_INVALID");
                }
                if !text.is_empty() {
                    m.insert((number(&c["row"])?, number(&c["column"])?), json!(text));
                }
            }
            Ok(m)
        };
        // Styles in the expected workbook are independently selected below.
        let mut expected_cells = std::collections::BTreeMap::new();
        for c in b["cells"].as_array().unwrap() {
            if let Some(t) = c["value"].as_str().filter(|s| !s.is_empty()) {
                expected_cells.insert((number(&c["row"])?, number(&c["column"])?), json!(t));
            }
        }
        if cells(a)? != expected_cells {
            return fail(422, "OUTPUT_BLOB_INVALID");
        }
    }
    Ok(())
}
fn published_dir(path: &Path) -> Result<()> {
    files::dir(path)
}
pub fn publish(source: &Path, root: &Path, name: &str, sha: &str) -> Result<PathBuf> {
    published_dir(root)?;
    let target = root.join(name);
    let same = || -> Result<()> {
        let m = fs::symlink_metadata(&target)?;
        if !m.is_file() || m.file_type().is_symlink() || m.len() > LIMIT as u64 {
            return fail(409, "OUTPUT_FILE_CONFLICT");
        }
        if hash(fs::read(&target)?) != sha {
            return fail(409, "OUTPUT_FILE_CONFLICT");
        }
        Ok(())
    };
    if target.exists() {
        same()?;
        return Ok(target);
    }
    let temporary = root.join(format!(".777-output-{}.partial", store::uid()?));
    let result = (|| -> Result<PathBuf> {
        let raw = files::read(source, LIMIT)?;
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        use std::io::Write;
        f.write_all(&raw)?;
        f.sync_all()?;
        drop(f);
        if hash(fs::read(&temporary)?) != sha {
            return fail(503, "OUTPUT_COPY_CHANGED");
        }
        let publish = files::publish_new(&temporary, &target);
        if let Err(e) = publish {
            if e.kind() != std::io::ErrorKind::AlreadyExists {
                return Err(e.into());
            }
        }
        same()?;
        Ok(target.clone())
    })();
    let _ = fs::remove_file(temporary);
    result
}
fn exact_cents(value: &Value, cents: i64) -> bool {
    let expected = cents.to_string();
    value.as_str() == Some(expected.as_str())
}

fn validate_order_binding(c: &Connection, o: &Value, admin: bool) -> Result<()> {
    let bad = || Error::new(503, "OUTPUT_LEDGER_BINDING_INVALID");
    let oid = o["order_id"].as_str().ok_or_else(bad)?;
    let revision = o["revision"].as_i64().filter(|r| *r > 0).ok_or_else(bad)?;
    let mut old = quote_ledger::editing::snapshot(c, oid)?["order"].clone();
    if store::verify(c)?["schema_version"]
        .as_i64()
        .is_some_and(|v| v >= 2)
    {
        let archive:Option<(i64,String)>=c.query_row("SELECT revision,snapshot_json FROM order_versions WHERE order_id=? AND revision>=? ORDER BY revision LIMIT 1",params![oid,revision],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        if let Some((rev, raw)) = archive {
            old = quote_ledger::editing::validate_archive(c, oid, rev, &raw)?["order"].clone();
        }
    }
    if old["revision"].as_i64().is_none_or(|r| r < revision)
        || serde_json::from_str::<Value>(old["details_json"].as_str().ok_or_else(bad)?)?
            != o["details"]
    {
        return Err(bad());
    }
    for k in if admin {
        vec!["income_cents", "cost_cents", "profit_cents"]
    } else {
        vec!["income_cents"]
    } {
        if !exact_cents(&o[k], old[k].as_i64().ok_or_else(bad)?) {
            return Err(bad());
        }
    }
    Ok(())
}
