//! Optional, explicitly enabled device identity store. No changes to auth-v1 or financial schema.
use crate::{
    auth::{self, Auth},
    fail, files, number,
    protocol::{fields, text},
    Error, Result,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_ledger::store::{hash, id, uid, Actor};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use subtle::ConstantTimeEq;
pub const FORMAT: &str = "777-device-auth-v1";
pub const APP: i64 = 0x37373744;
pub const DDL: &str = include_str!("../../../docs/verification/P07-02-device-schema.sql");
pub struct Devices {
    pub path: PathBuf,
}
fn secret(v: &Value) -> Result<&str> {
    let s = text(v, 43, true)?;
    if s.len() != 43
        || !s
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return fail(401, "DEVICE_NOT_AUTHORIZED");
    };
    Ok(s)
}
fn delivery(v: &Value) -> Result<&str> {
    let s = text(v, 16, true)?;
    if !["manager", "sales"].contains(&s) {
        return fail(422, "INVALID_DELIVERY");
    };
    Ok(s)
}
fn role(kind: &str) -> &str {
    if kind == "manager" {
        "admin"
    } else {
        "sales"
    }
}
impl Devices {
    pub fn create(path: &Path) -> Result<Self> {
        files::new_file(path, &[])?;
        let c = Connection::open(path)?;
        c.execute_batch(DDL)?;
        c.pragma_update(None, "application_id", APP)?;
        c.pragma_update(None, "user_version", 1)?;
        drop(c);
        Self::open(path.into())
    }
    pub fn open(path: PathBuf) -> Result<Self> {
        files::database(&path, APP, DDL)?;
        Ok(Self { path })
    }
    fn connection(&self) -> Result<Connection> {
        files::database(&self.path, APP, DDL)
    }
    fn user(auth: &Auth, subject: &str) -> Result<(String, String, i64)> {
        auth.connection()?
            .query_row(
                "SELECT username,role,epoch FROM users WHERE id=? AND enabled=1",
                [subject],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?
            .ok_or_else(|| Error::new(401, "DEVICE_NOT_AUTHORIZED"))
    }
    fn audit(c: &Connection, a: &str, op: &str, target: &str) -> Result<()> {
        c.execute(
            "INSERT INTO device_audit(actor,operation,target,at) VALUES(?,?,?,?)",
            params![a, op, target, auth::now()],
        )?;
        Ok(())
    }
    pub fn issue(&self, auth: &Auth, a: &Actor, v: &Value) -> Result<Value> {
        Auth::admin(a)?;
        fields(v, &["subject", "delivery", "ttl_seconds"], &[])?;
        let subject = text(&v["subject"], 36, true)?;
        id(subject)?;
        let kind = delivery(&v["delivery"])?;
        let ttl = number(&v["ttl_seconds"])?;
        if !(30..=3600).contains(&ttl) {
            return fail(422, "INVALID_GRANT_LIFETIME");
        };
        let (_, r, epoch) = Self::user(auth, subject)?;
        if r != role(kind) {
            return fail(403, "DELIVERY_ROLE_MISMATCH");
        };
        let ticket = URL_SAFE_NO_PAD.encode(auth::random::<32>()?);
        let key = uid()?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        tx.execute(
            "DELETE FROM grants WHERE expires<? AND device_id IS NULL",
            [auth::now()],
        )?;
        if tx.query_row("SELECT count(*) FROM grants", [], |r| r.get::<_, i64>(0))? > 10000 {
            return fail(429, "DEVICE_CAPACITY");
        };
        tx.execute(
            "INSERT INTO grants VALUES(?,?,?,?,?,?,NULL,NULL)",
            params![key, hash(&ticket), subject, kind, epoch, auth::now() + ttl],
        )?;
        Self::audit(&tx, &a.subject, "grant_issued", &key)?;
        tx.commit()?;
        Ok(
            json!({"protocol":FORMAT,"grant_id":key,"ticket":ticket,"subject":subject,"delivery":kind,"expires":auth::now()+ttl}),
        )
    }
    pub fn enroll(&self, auth: &Auth, v: &Value) -> Result<Value> {
        fields(
            v,
            &["ticket", "device_id", "device_secret", "delivery"],
            &[],
        )?;
        let ticket = secret(&v["ticket"])?;
        let key = text(&v["device_id"], 36, true)?;
        id(key)?;
        let digest = hash(secret(&v["device_secret"])?);
        let kind = delivery(&v["delivery"])?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        type Grant = (String, String, i64, i64, Option<String>, Option<String>);
        let row:Option<Grant>=tx.query_row("SELECT subject,delivery,epoch,expires,device_id,credential FROM grants WHERE digest=?",[hash(ticket)],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional()?;
        let (subject, expected, epoch, expires, used, credential) =
            row.ok_or_else(|| Error::new(401, "DEVICE_NOT_AUTHORIZED"))?;
        let (_, r, current) = Self::user(auth, &subject)?;
        if expected != kind || r != role(kind) || current != epoch {
            return fail(403, "DELIVERY_ROLE_MISMATCH");
        };
        if let Some(used) = used {
            if used != key
                || credential.as_deref() != Some(digest.as_str())
                || !tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM devices WHERE id=? AND enabled=1)",
                    [key],
                    |r| r.get::<_, bool>(0),
                )?
            {
                return fail(401, "DEVICE_NOT_AUTHORIZED");
            };
        } else {
            if expires <= auth::now() {
                return fail(401, "DEVICE_NOT_AUTHORIZED");
            };
            if tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM devices WHERE id=?)",
                [key],
                |r| r.get::<_, bool>(0),
            )? {
                return fail(409, "DEVICE_ID_CONFLICT");
            };
            tx.execute(
                "INSERT INTO devices VALUES(?,?,?,?,?,1,?)",
                params![key, subject, kind, epoch, digest, auth::now()],
            )?;
            tx.execute(
                "UPDATE grants SET device_id=?,credential=? WHERE digest=?",
                params![key, digest, hash(ticket)],
            )?;
            Self::audit(&tx, &subject, "device_enrolled", key)?;
        }
        tx.commit()?;
        Ok(json!({"protocol":FORMAT,"device_id":key,"subject":subject,"delivery":kind}))
    }
    pub fn session(&self, auth: &Auth, v: &Value) -> Result<Value> {
        fields(v, &["device_id", "device_secret", "delivery"], &[])?;
        let key = text(&v["device_id"], 36, true)?;
        id(key)?;
        let digest = hash(secret(&v["device_secret"])?);
        let kind = delivery(&v["delivery"])?;
        let c = self.connection()?;
        let row: Option<(String, String, i64, String)> = c
            .query_row(
                "SELECT subject,delivery,epoch,credential FROM devices WHERE id=? AND enabled=1",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()?;
        let (subject, expected, epoch, credential) =
            row.ok_or_else(|| Error::new(401, "DEVICE_NOT_AUTHORIZED"))?;
        let (user, r, current) = Self::user(auth, &subject)?;
        if digest.as_bytes().ct_eq(credential.as_bytes()).unwrap_u8() != 1
            || expected != kind
            || current != epoch
            || r != role(kind)
        {
            return fail(401, "DEVICE_NOT_AUTHORIZED");
        };
        let token = URL_SAFE_NO_PAD.encode(auth::random::<32>()?);
        let tx = c.unchecked_transaction()?;
        tx.execute(
            "DELETE FROM device_sessions WHERE expires<=? OR device_id=?",
            params![auth::now(), key],
        )?;
        tx.execute(
            "INSERT INTO device_sessions VALUES(?,?,?)",
            params![hash(&token), key, auth::now() + 28800],
        )?;
        tx.commit()?;
        Ok(
            json!({"protocol":FORMAT,"token":token,"subject":subject,"role":r,"username":user,"expires":auth::now()+28800}),
        )
    }
    pub fn authenticate(&self, auth: &Auth, token: &str) -> Result<Actor> {
        secret(&json!(token)).map_err(|_| Error::new(401, "UNAUTHENTICATED"))?;
        let row:Option<(String,String,i64)>=self.connection()?.query_row("SELECT d.subject,d.delivery,d.epoch FROM devices d JOIN device_sessions s ON d.id=s.device_id WHERE s.digest=? AND s.expires>? AND d.enabled=1",params![hash(token),auth::now()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        let (subject, kind, epoch) = row.ok_or_else(|| Error::new(401, "UNAUTHENTICATED"))?;
        let (_, r, current) = Self::user(auth, &subject)?;
        if current != epoch || r != role(&kind) {
            return fail(401, "UNAUTHENTICATED");
        };
        Ok(Actor { subject, role: r })
    }
    pub fn logout(&self, token: &str) -> Result<()> {
        self.connection()?
            .execute("DELETE FROM device_sessions WHERE digest=?", [hash(token)])?;
        Ok(())
    }
    pub fn listing(&self, a: &Actor) -> Result<Value> {
        Auth::admin(a)?;
        let c = self.connection()?;
        let mut st = c.prepare(
            "SELECT id,subject,delivery,enabled,created FROM devices ORDER BY created,id",
        )?;
        let rows=st.query_map([],|r|Ok(json!({"device_id":r.get::<_,String>(0)?,"subject":r.get::<_,String>(1)?,"delivery":r.get::<_,String>(2)?,"enabled":r.get::<_,i64>(3)?==1,"created":r.get::<_,i64>(4)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
        Ok(json!({"devices":rows}))
    }
    pub fn revoke(&self, a: &Actor, key: &str) -> Result<Value> {
        Auth::admin(a)?;
        id(key)?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        if tx.execute("UPDATE devices SET enabled=0 WHERE id=?", [key])? != 1 {
            return fail(404, "NOT_FOUND");
        };
        tx.execute("DELETE FROM device_sessions WHERE device_id=?", [key])?;
        Self::audit(&tx, &a.subject, "device_revoked", key)?;
        tx.commit()?;
        Ok(json!({"device_id":key,"revoked":true}))
    }
    pub fn validate_accounts(&self, auth: &Auth) -> Result<()> {
        let c = self.connection()?;
        let mut st = c.prepare("SELECT subject FROM devices UNION SELECT subject FROM grants")?;
        let users = st
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let accounts = auth.connection()?;
        for subject in users {
            if !accounts.query_row(
                "SELECT EXISTS(SELECT 1 FROM users WHERE id=?)",
                [subject],
                |r| r.get::<_, bool>(0),
            )? {
                return fail(503, "DEVICE_ACCOUNT_MAPPING_INCOMPLETE");
            }
        }
        Ok(())
    }
    pub fn revoke_all(&self) -> Result<()> {
        let c = self.connection()?;
        c.execute_batch("BEGIN;DELETE FROM device_sessions;UPDATE devices SET enabled=0;DELETE FROM grants;COMMIT;")?;
        Ok(())
    }
}
