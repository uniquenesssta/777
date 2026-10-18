use crate::{
    casefold, fail, files, number,
    protocol::{self, text},
    Error, Result,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_ledger::store::{encoded, hash, uid, Actor};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use subtle::ConstantTimeEq;
pub const DDL: &str = include_str!("../../../docs/verification/P06-04-auth-schema.sql");
pub const APP: i64 = 0x37373741;
pub fn now() -> i64 {
    time::OffsetDateTime::now_utc().unix_timestamp()
}
pub fn username(v: &Value) -> Result<String> {
    let s = text(v, 64, true)?;
    if quote_core::numbers::trim(s) != s || s.chars().count() < 3 || s.chars().any(|c| c < ' ') {
        return fail(422, "INVALID_USERNAME");
    }
    Ok(casefold(s))
}
pub fn password(v: &Value) -> Result<&str> {
    let s = text(v, 128, false)?;
    if s.chars().count() < 12 || s.len() > 512 {
        return fail(422, "PASSWORD_LENGTH_12_TO_128");
    }
    Ok(s)
}
pub fn random<const N: usize>() -> Result<[u8; N]> {
    let mut b = [0; N];
    getrandom::getrandom(&mut b).map_err(|_| Error::new(503, "RANDOM_UNAVAILABLE"))?;
    Ok(b)
}
pub fn verifier(secret: &str, salt: &[u8]) -> Result<Vec<u8>> {
    let p = scrypt::Params::new(15, 8, 1, 32).map_err(|_| Error::new(503, "AUTH_UNAVAILABLE"))?;
    let mut out = vec![0; 32];
    scrypt::scrypt(secret.as_bytes(), salt, &p, &mut out)
        .map_err(|_| Error::new(503, "AUTH_UNAVAILABLE"))?;
    Ok(out)
}
pub struct Auth {
    pub path: PathBuf,
    attempts: HashMap<(String, String), (usize, i64)>,
}
impl Auth {
    pub fn open(path: PathBuf) -> Result<Self> {
        files::database(&path, APP, DDL)?;
        Ok(Self {
            path,
            attempts: HashMap::new(),
        })
    }
    pub fn connection(&self) -> Result<Connection> {
        files::database(&self.path, APP, DDL)
    }
    pub fn create(path: &Path, user: &str, secret: &str) -> Result<Self> {
        let user = username(&json!(user))?;
        password(&json!(secret))?;
        files::new_file(path, &[])?;
        let c = Connection::open(path)?;
        c.execute_batch(DDL)?;
        c.pragma_update(None, "application_id", APP)?;
        c.pragma_update(None, "user_version", 1)?;
        let tx = c.unchecked_transaction()?;
        let salt = random::<16>()?;
        tx.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,1,1)",
            params![
                uid()?,
                user,
                "admin",
                salt.as_slice(),
                verifier(secret, &salt)?
            ],
        )?;
        tx.execute_batch("INSERT INTO preferences VALUES(1,1,'','');INSERT INTO backup_plan VALUES(1,1,30,2,48,30,480);INSERT INTO backup_health VALUES(1,NULL,NULL,0);")?;
        tx.commit()?;
        drop(c);
        Self::open(path.into())
    }
    pub fn admin(a: &Actor) -> Result<()> {
        if a.role != "admin" {
            return fail(403, "FORBIDDEN");
        }
        Ok(())
    }
    pub fn login(&mut self, user: &Value, secret: &Value, peer: &str) -> Result<Value> {
        let user = username(user)?;
        let secret = text(secret, 128, false)?;
        if secret.len() > 512 {
            return fail(401, "UNAUTHENTICATED");
        }
        let at = now();
        self.attempts.retain(|_, v| at - v.1 < 300);
        let key = (peer.into(), user.clone());
        let peerkey = (peer.into(), "*".into());
        let a = *self.attempts.get(&key).unwrap_or(&(0, at));
        let b = *self.attempts.get(&peerkey).unwrap_or(&(0, at));
        if a.0 >= 5 || b.0 >= 20 || self.attempts.len() >= 2048 {
            return fail(429, "LOGIN_RATE_LIMIT");
        }
        let c = self.connection()?;
        type UserRow = (String, String, Vec<u8>, Vec<u8>, i64, i64);
        let row: Option<UserRow> = c
            .query_row(
                "SELECT id,role,salt,verifier,enabled,epoch FROM users WHERE username=?",
                [&user],
                |r| {
                    Ok((
                        r.get(0)?,
                        r.get(1)?,
                        r.get(2)?,
                        r.get(3)?,
                        r.get(4)?,
                        r.get(5)?,
                    ))
                },
            )
            .optional()?;
        let (salt, expected) = row
            .as_ref()
            .map(|r| (r.2.as_slice(), r.3.as_slice()))
            .unwrap_or((b"777-no-such-user!", &[0u8; 32]));
        let good = verifier(secret, salt)?.ct_eq(expected).unwrap_u8() == 1;
        let device_only = if crate::automatic::schema::enabled(&c)? {
            row.as_ref().map(|r| c.query_row("SELECT EXISTS(SELECT 1 FROM principal_modes WHERE subject=? AND mode='device_only')", [&r.0], |r|r.get::<_,bool>(0))).transpose()?.unwrap_or(false)
        } else {
            false
        };
        if !good || device_only || row.as_ref().is_none_or(|r| r.4 != 1) {
            self.attempts.insert(key, (a.0 + 1, a.1));
            self.attempts.insert(peerkey, (b.0 + 1, b.1));
            return fail(401, "UNAUTHENTICATED");
        }
        let r = row.unwrap();
        let token = URL_SAFE_NO_PAD.encode(random::<32>()?);
        let tx = c.unchecked_transaction()?;
        tx.execute("DELETE FROM sessions WHERE expires<=?", [at])?;
        tx.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            params![hash(&token), r.0, r.5, at + 28800],
        )?;
        tx.commit()?;
        self.attempts.remove(&key);
        Ok(json!({"token":token,"expires":at+28800,"subject":r.0,"role":r.1}))
    }
    pub fn authenticate(&self, token: &str) -> Result<Actor> {
        if token.len() != 43
            || !token
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return fail(401, "UNAUTHENTICATED");
        }
        let c = self.connection()?;
        let r:Option<(String,String,i64,i64,i64,i64)>=c.query_row("SELECT u.id,u.role,u.enabled,u.epoch,s.epoch,s.expires FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.digest=?",[hash(token)],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional()?;
        match r {
            Some((subject, role, 1, epoch, sess, exp)) if epoch == sess && exp > now() => {
                Ok(Actor { subject, role })
            }
            _ => fail(401, "UNAUTHENTICATED"),
        }
    }
    pub fn logout(&self, token: &str) -> Result<Value> {
        self.connection()?
            .execute("DELETE FROM sessions WHERE digest=?", [hash(token)])?;
        Ok(json!({"logged_out":true}))
    }
    pub fn audit(c: &Connection, a: &Actor, op: &str, target: &str) -> Result<()> {
        c.execute(
            "INSERT INTO auth_audit(actor,operation,target,at) VALUES(?,?,?,?)",
            params![a.subject, op, target, now()],
        )?;
        Ok(())
    }
    pub fn accounts(&self, a: &Actor) -> Result<Value> {
        Self::admin(a)?;
        let c = self.connection()?;
        let mut st =
            c.prepare("SELECT id,username,role,enabled,epoch FROM users ORDER BY username")?;
        let rows=st.query_map([],|r|Ok(json!({"id":r.get::<_,String>(0)?,"username":r.get::<_,String>(1)?,"role":r.get::<_,String>(2)?,"enabled":r.get::<_,i64>(3)?,"epoch":r.get::<_,i64>(4)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
        Ok(json!({"accounts":rows}))
    }
    pub fn create_account(&self, a: &Actor, data: &Value) -> Result<Value> {
        Self::admin(a)?;
        protocol::fields(data, &["username", "password", "role"], &[])?;
        let user = username(&data["username"])?;
        let secret = password(&data["password"])?;
        let role = text(&data["role"], 16, true)?;
        if !["admin", "sales"].contains(&role) {
            return fail(422, "INVALID_ROLE");
        }
        let salt = random::<16>()?;
        let key = uid()?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        tx.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,1,1)",
            params![key, user, role, salt.as_slice(), verifier(secret, &salt)?],
        )?;
        Self::audit(&tx, a, "account_created", &key)?;
        tx.commit()?;
        Ok(json!({"id":key,"username":user,"role":role}))
    }
    pub fn update_account(&self, a: &Actor, key: &str, data: &Value) -> Result<Value> {
        Self::admin(a)?;
        let o = protocol::fields(data, &[], &["password", "role", "enabled"])?;
        if o.is_empty() {
            return fail(422, "INVALID_FIELDS");
        }
        if data
            .get("role")
            .is_some_and(|x| !x.is_null() && x != "admin" && x != "sales")
            || data
                .get("enabled")
                .is_some_and(|x| !x.is_null() && !x.is_boolean())
        {
            return fail(422, "INVALID_ACCOUNT");
        }
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        let row: Option<(String, i64, Vec<u8>, Vec<u8>)> = tx
            .query_row(
                "SELECT role,enabled,salt,verifier FROM users WHERE id=?",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()?;
        let (role, on, mut salt, mut hashed) = row.ok_or_else(|| Error::new(404, "NOT_FOUND"))?;
        let next_role = data["role"].as_str().unwrap_or(&role);
        let next_on = data["enabled"].as_bool().map(i64::from).unwrap_or(on);
        let admin_count: i64 = if crate::automatic::schema::enabled(&tx)? {
            tx.query_row("SELECT count(*) FROM users WHERE role='admin' AND enabled=1 AND id NOT IN (SELECT subject FROM principal_modes WHERE mode='device_only')",[],|r|r.get(0))?
        } else {
            tx.query_row(
                "SELECT count(*) FROM users WHERE role='admin' AND enabled=1",
                [],
                |r| r.get(0),
            )?
        };
        let legacy_target = if crate::automatic::schema::enabled(&tx)? {
            !tx.query_row("SELECT EXISTS(SELECT 1 FROM principal_modes WHERE subject=? AND mode='device_only')",[key],|r|r.get::<_,bool>(0))?
        } else {
            true
        };
        if role == "admin"
            && legacy_target
            && on == 1
            && (next_role != "admin" || next_on != 1)
            && admin_count <= 1
        {
            return fail(409, "LAST_ADMIN_REQUIRED");
        }
        if let Some(secret) = data.get("password").filter(|v| !v.is_null()) {
            salt = random::<16>()?.to_vec();
            hashed = verifier(password(secret)?, &salt)?;
        }
        tx.execute(
            "UPDATE users SET role=?,enabled=?,salt=?,verifier=?,epoch=epoch+1 WHERE id=?",
            params![next_role, next_on, salt, hashed, key],
        )?;
        tx.execute("DELETE FROM sessions WHERE user_id=?", [key])?;
        Self::audit(&tx, a, "account_updated", key)?;
        tx.commit()?;
        Ok(json!({"id":key,"role":next_role,"enabled":next_on!=0}))
    }
    pub fn preferences(&self) -> Result<Value> {
        Ok(self.connection()?.query_row("SELECT revision,export_dir,image_dir FROM preferences WHERE id=1",[],|r|Ok(json!({"revision":r.get::<_,i64>(0)?,"export_dir":r.get::<_,String>(1)?,"image_dir":r.get::<_,String>(2)?})))?)
    }
    pub fn save_preferences(&self, a: &Actor, data: &Value) -> Result<Value> {
        Self::admin(a)?;
        protocol::fields(data, &["revision", "export_dir", "image_dir"], &[])?;
        let revision = number(&data["revision"])?;
        let export = directory(&data["export_dir"])?;
        let image = directory(&data["image_dir"])?;
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        if tx.query_row("SELECT revision FROM preferences WHERE id=1", [], |r| {
            r.get::<_, i64>(0)
        })? != revision
        {
            return fail(409, "SETTINGS_REVISION_CONFLICT");
        }
        tx.execute(
            "UPDATE preferences SET revision=revision+1,export_dir=?,image_dir=? WHERE id=1",
            params![export, image],
        )?;
        Self::audit(&tx, a, "directories_published", "preferences")?;
        tx.commit()?;
        self.preferences()
    }
    pub fn backup_plan(&self) -> Result<Value> {
        Ok(self.connection()?.query_row("SELECT revision,interval_minutes,daily_hour,rolling,daily,offset_minutes FROM backup_plan WHERE id=1",[],|r|Ok(json!({"revision":r.get::<_,i64>(0)?,"interval_minutes":r.get::<_,i64>(1)?,"daily_hour":r.get::<_,i64>(2)?,"rolling":r.get::<_,i64>(3)?,"daily":r.get::<_,i64>(4)?,"offset_minutes":r.get::<_,i64>(5)?})))?)
    }
    pub fn save_backup_plan(&self, a: &Actor, v: &Value) -> Result<Value> {
        Self::admin(a)?;
        let ranges = [
            ("revision", 1, i64::MAX - 1),
            ("interval_minutes", 1, 1440),
            ("daily_hour", 0, 23),
            ("rolling", 1, 512),
            ("daily", 1, 366),
            ("offset_minutes", -720, 840),
        ];
        protocol::fields(v, &ranges.map(|r| r.0), &[])?;
        for (k, lo, hi) in ranges {
            let n = number(&v[k])?;
            if n < lo || n > hi {
                return fail(422, "INVALID_BACKUP_PLAN");
            }
        }
        let c = self.connection()?;
        let tx = c.unchecked_transaction()?;
        if tx.query_row("SELECT revision FROM backup_plan WHERE id=1", [], |r| {
            r.get::<_, i64>(0)
        })? != number(&v["revision"])?
        {
            return fail(409, "SETTINGS_REVISION_CONFLICT");
        }
        tx.execute("UPDATE backup_plan SET revision=revision+1,interval_minutes=?,daily_hour=?,rolling=?,daily=?,offset_minutes=? WHERE id=1",params![number(&v["interval_minutes"])?,number(&v["daily_hour"])?,number(&v["rolling"])?,number(&v["daily"])?,number(&v["offset_minutes"])?])?;
        Self::audit(&tx, a, "backup_plan_published", "backup_plan")?;
        tx.commit()?;
        self.backup_plan()
    }
    pub fn backup_health(&self) -> Result<Value> {
        let c = self.connection()?;
        let (raw, error, at): (Option<String>, Option<String>, i64) = c.query_row(
            "SELECT last_success_json,error,at FROM backup_health WHERE id=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        Ok(
            json!({"last_success":raw.map(|r|serde_json::from_str::<Value>(&r)).transpose()?,"error":error,"at":at}),
        )
    }
    pub fn record_backup(&self, result: Option<&Value>, error: Option<&str>) -> Result<()> {
        let c = self.connection()?;
        if let Some(v) = result {
            c.execute(
                "UPDATE backup_health SET last_success_json=?,error=NULL,at=? WHERE id=1",
                params![encoded(v), now()],
            )?;
        } else {
            c.execute(
                "UPDATE backup_health SET error=?,at=? WHERE id=1",
                params![error, now()],
            )?;
        }
        Ok(())
    }
}
fn directory(v: &Value) -> Result<String> {
    let s = quote_core::numbers::trim(text(v, 32767, true)?);
    if s.chars().any(|c| c < ' ') {
        return fail(422, "INVALID_PUBLISHED_DIRECTORY");
    }
    if !quote_ledger::paths::absolute(Path::new(s)) {
        return fail(422, "INVALID_PUBLISHED_DIRECTORY");
    }
    Ok(s.to_string())
}
