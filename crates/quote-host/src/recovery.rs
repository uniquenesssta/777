//! Versioned logical business backup. Contains no programs or authentication secrets.
use crate::{auth, fail, files, host, outputs::Outputs, service::Service, Error, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::{integrity, store};
use rusqlite::{types::Value as SqlValue, Connection};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::BTreeMap, fs, path::Path};
pub const FORMAT: &str = "777-data-backup-v1";
pub const LIMIT: usize = 256 * 1024 * 1024;
const LEDGER: [&str; 8] = [
    "price_versions",
    "requests",
    "orders",
    "lines",
    "notes",
    "import_batches",
    "audit_events",
    "ledger_meta",
];
const OUTPUT: [&str; 3] = ["jobs", "receipts", "events"];
#[derive(Serialize, Deserialize, Clone, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Table {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Value>>,
}
#[derive(Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct Data {
    pub format: String,
    pub snapshot_id: String,
    pub created_at: String,
    pub business_date: String,
    pub source_version: String,
    pub inventory: Value,
    pub ledger: BTreeMap<String, Table>,
    pub users: Table,
    pub outputs: BTreeMap<String, Table>,
    pub blobs: BTreeMap<String, String>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    format: String,
    sha256: String,
    data: Data,
}
fn invalid() -> Error {
    Error::new(422, "DATA_BACKUP_INVALID")
}
fn table(c: &Connection, sql: &str) -> Result<Table> {
    let mut st = c.prepare(sql)?;
    let columns = st
        .column_names()
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
    let n = columns.len();
    let rows = st
        .query_map([], |r| {
            (0..n)
                .map(|i| match r.get::<_, SqlValue>(i)? {
                    SqlValue::Null => Ok(Value::Null),
                    SqlValue::Integer(v) => Ok(json!(v)),
                    SqlValue::Text(v) => Ok(json!(v)),
                    _ => Err(rusqlite::Error::InvalidQuery),
                })
                .collect::<std::result::Result<Vec<_>, _>>()
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(Table { columns, rows })
}
pub fn capture(s: &Service, date: &str) -> Result<Data> {
    crate::backup::accounts(&s.ledger, &s.auth)?;
    let c = store::open(&s.ledger, false)?;
    let _tx = c.unchecked_transaction()?;
    let inventory = integrity::inventory(&c)?;
    let ledger = LEDGER
        .into_iter()
        .map(|n| {
            Ok((
                n.into(),
                table(&c, &format!("SELECT * FROM {n} ORDER BY rowid"))?,
            ))
        })
        .collect::<Result<_>>()?;
    let users = table(
        &s.auth.connection()?,
        "SELECT id,username,role,enabled FROM users ORDER BY id",
    )?;
    let mut outputs = BTreeMap::new();
    let mut blobs = BTreeMap::new();
    if let Some(o) = &s.outputs {
        for name in o.validate_ledger(&s.ledger)? {
            blobs.insert(
                name.clone(),
                STANDARD.encode(files::read(&s.root.join("private").join(&name), LIMIT)?),
            );
        }
        let oc = o.connection()?;
        for name in OUTPUT {
            outputs.insert(
                name.into(),
                table(&oc, &format!("SELECT * FROM {name} ORDER BY rowid"))?,
            );
        }
    }
    Ok(Data {
        format: FORMAT.into(),
        snapshot_id: store::uid()?,
        created_at: store::now(),
        business_date: date.into(),
        source_version: env!("CARGO_PKG_VERSION").into(),
        inventory,
        ledger,
        users,
        outputs,
        blobs,
    })
}
pub fn encode(data: &Data) -> Result<Vec<u8>> {
    let raw = serde_json::to_vec(data)?;
    let result = serde_json::to_vec(&Envelope {
        format: FORMAT.into(),
        sha256: store::hash(&raw),
        data: data.clone(),
    })?;
    if result.len() > LIMIT {
        return fail(413, "DATA_BACKUP_TOO_LARGE");
    };
    Ok(result)
}
pub fn decode(raw: &[u8]) -> Result<Data> {
    if raw.len() > LIMIT {
        return fail(413, "DATA_BACKUP_TOO_LARGE");
    }
    let e: Envelope = serde_json::from_slice(raw).map_err(|_| invalid())?;
    if e.format != FORMAT || e.data.format != FORMAT {
        return fail(422, "DATA_BACKUP_VERSION_UNSUPPORTED");
    }
    if store::hash(serde_json::to_vec(&e.data)?) != e.sha256 {
        return fail(422, "DATA_BACKUP_HASH_INVALID");
    }
    store::id(&e.data.snapshot_id)?;
    store::id(e.data.inventory["ledger_id"].as_str().ok_or_else(invalid)?)?;
    if e.data.ledger.len() != LEDGER.len()
        || LEDGER.iter().any(|n| !e.data.ledger.contains_key(*n))
        || (!e.data.outputs.is_empty()
            && (e.data.outputs.len() != OUTPUT.len()
                || OUTPUT.iter().any(|n| !e.data.outputs.contains_key(*n))))
    {
        return Err(invalid());
    }
    Ok(e.data)
}
fn insert(c: &Connection, name: &str, t: &Table) -> Result<()> {
    let expected = table(c, &format!("SELECT * FROM {name} LIMIT 0"))?;
    if expected.columns != t.columns {
        return fail(422, "DATA_BACKUP_VERSION_UNSUPPORTED");
    }
    let sql = format!(
        "INSERT INTO {name} VALUES({})",
        vec!["?"; t.columns.len()].join(",")
    );
    let mut st = c.prepare(&sql)?;
    for row in &t.rows {
        if row.len() != t.columns.len() {
            return Err(invalid());
        }
        let v = row
            .iter()
            .map(|v| match v {
                Value::Null => Ok(SqlValue::Null),
                Value::String(s) => Ok(SqlValue::Text(s.clone())),
                Value::Number(n) => n.as_i64().map(SqlValue::Integer).ok_or_else(invalid),
                _ => Err(invalid()),
            })
            .collect::<Result<Vec<_>>>()?;
        st.execute(rusqlite::params_from_iter(v))?;
    }
    Ok(())
}
pub fn restore_ledger(data: &Data, path: &Path) -> Result<()> {
    store::create(path)?;
    fill_ledger(data, path)
}
fn fill_ledger(data: &Data, path: &Path) -> Result<()> {
    let mut c = store::open(path, true)?;
    let tx = c.transaction()?;
    tx.execute_batch("PRAGMA defer_foreign_keys=ON;DELETE FROM ledger_meta;")?;
    for name in LEDGER {
        insert(&tx, name, &data.ledger[name])?;
    }
    if integrity::inventory(&tx)? != data.inventory {
        return fail(422, "DATA_BACKUP_INVENTORY_MISMATCH");
    }
    tx.commit()?;
    Ok(())
}
/// Restores only into new host/backup roots. Existing hosts are never overwritten.
pub fn restore(path: &Path, init: host::Init) -> Result<Value> {
    let data = decode(&files::read(path, LIMIT)?)?;
    if init.root.exists() || init.backups.exists() {
        return fail(409, "RESTORE_REQUIRES_NEW_DIRECTORY");
    }
    let root = init.root.clone();
    let backups = init.backups.clone();
    let auxiliary = init.auxiliary;
    // Validate the logical ledger before allocating the new host.
    let check = root.with_file_name(format!(".restore-check-{}", store::uid()?));
    let checked = restore_ledger(&data, &check);
    if check.exists() {
        fs::remove_file(&check)?;
    }
    checked?;
    let new_user = init.user.clone();
    let result = (|| {
        let mut config = host::initialize(init)?;
        let private = root.join("private");
        fill_ledger(&data, &private.join("ledger.sqlite3"))?;
        let a = auth::Auth::open(private.join("auth.sqlite3"))?;
        let c = a.connection()?;
        if data.users.columns != ["id", "username", "role", "enabled"] {
            return Err(invalid());
        }
        for row in &data.users.rows {
            if row.len() != 4 {
                return Err(invalid());
            }
            let id = row[0].as_str().ok_or_else(invalid)?;
            store::id(id)?;
            let name = auth::username(&row[1])?;
            if name == new_user {
                return fail(409, "RECOVERY_ACCOUNT_NAME_CONFLICT");
            }
            let role = row[2]
                .as_str()
                .filter(|v| ["admin", "sales"].contains(v))
                .ok_or_else(invalid)?;
            c.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,0,1)",
                rusqlite::params![
                    id,
                    name,
                    role,
                    auth::random::<16>()?.as_slice(),
                    auth::random::<32>()?.as_slice()
                ],
            )?;
        }
        // Historical actors remain mapped but all old credentials are invalidated.
        crate::backup::accounts(&private.join("ledger.sqlite3"), &a)?;
        config["ledger_id"] = data.inventory["ledger_id"].clone();
        files::replace_json(&private.join("service.json"), &config)?;
        let output_path = private.join("outputs.sqlite3");
        let oc = Connection::open(&output_path)?;
        oc.execute(
            "UPDATE meta SET ledger_id=?",
            [data.inventory["ledger_id"].as_str().ok_or_else(invalid)?],
        )?;
        let tx = oc.unchecked_transaction()?;
        if !data.outputs.is_empty() {
            for name in OUTPUT {
                insert(&tx, name, &data.outputs[name])?;
            }
        }
        // A restored job must never replay writes to a path from the original computer.
        tx.execute("UPDATE jobs SET state='failed',error='RESTORED_REQUIRES_EXPLICIT_RETRY',output_path=NULL WHERE state IN ('queued','running')",[])?;
        tx.commit()?;
        drop(oc);
        for (name, encoded) in &data.blobs {
            let tail = name.strip_prefix("output-blobs/").ok_or_else(invalid)?;
            let (id, ext) = tail.rsplit_once('.').ok_or_else(invalid)?;
            store::id(id)?;
            if !["png", "xlsx"].contains(&ext) {
                return Err(invalid());
            }
            let raw = STANDARD.decode(encoded).map_err(|_| invalid())?;
            files::new_file(&private.join(name), &raw)?;
        }
        let o = Outputs::open(
            output_path,
            data.inventory["ledger_id"].as_str().ok_or_else(invalid)?,
        )?;
        let names = o.validate_ledger(&private.join("ledger.sqlite3"))?;
        if names.len() != data.blobs.len() || names.iter().any(|n| !data.blobs.contains_key(n)) {
            return Err(invalid());
        }
        // Reusing a current-day backup also reuses its daily identity, including at the hidden destination.
        let today = time::OffsetDateTime::now_utc()
            .to_offset(time::UtcOffset::from_hms(8, 0, 0).unwrap())
            .date()
            .to_string();
        if data.business_date == today {
            let caches = private.join("daily-cache");
            files::new_dir(&caches)?;
            let cache = caches.join(&today);
            files::new_dir(&cache)?;
            files::new_file(&cache.join("data.qbackup"), &encode(&data)?)?;
            let excel = quote_excel::backup::write(&serde_json::to_value(&data)?)
                .map_err(|e| Error::new(422, &e.code))?;
            files::new_file(&cache.join("data.xlsx"), &excel)?;
        }
        Service::load(&root, auxiliary, false)?;
        Ok(
            json!({"status":"restored","snapshot_id":data.snapshot_id,"inventory":data.inventory,"root":root.to_string_lossy()}),
        )
    })();
    if result.is_err() {
        if root.exists() {
            let _ = fs::remove_dir_all(&root);
        }
        if backups.exists() {
            let _ = fs::remove_dir_all(&backups);
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn published_v1_fixture_survives_source_version_changes_with_exact_rows() {
        let raw = include_bytes!("../../../tests/fixtures/p07-06-data-v1.qbackup");
        let mut data = decode(raw).unwrap();
        data.source_version = "99.0.0".into();
        let decoded = decode(&encode(&data).unwrap()).unwrap();
        let path = std::env::temp_dir().join(format!("777-v1-{}.sqlite3", store::uid().unwrap()));
        restore_ledger(&decoded, &path).unwrap();
        {
            let c = store::open(&path, false).unwrap();
            for name in LEDGER {
                assert!(
                    table(&c, &format!("SELECT * FROM {name} ORDER BY rowid")).unwrap()
                        == decoded.ledger[name]
                );
            }
        }
        fs::remove_file(path).unwrap();
    }
}
