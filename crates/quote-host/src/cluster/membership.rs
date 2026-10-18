use super::config;
use crate::{auth, fail, files, Error, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_ledger::store::{hash, id, uid};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::path::Path;
use subtle::ConstantTimeEq;
pub const APP: i64 = 0x37373743;
pub const DDL: &str = include_str!("../../../../docs/verification/P08-02-cluster-schema.sql");
pub fn credential() -> Result<String> {
    Ok(URL_SAFE_NO_PAD.encode(auth::random::<32>()?))
}
pub fn validate_secret(value: &str) -> Result<()> {
    if value.len() != 43
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return fail(401, "CLUSTER_NOT_AUTHORIZED");
    }
    Ok(())
}
pub fn create(root: &Path) -> Result<()> {
    let path = config::directory(root).join("peers.sqlite3");
    if path.exists() {
        return fail(409, "CLUSTER_MEMBERSHIP_ALREADY_EXISTS");
    }
    let stage = config::directory(root).join(format!("peers-{}.partial", uid()?));
    files::new_file(&stage, &[])?;
    let result = (|| {
        let c = Connection::open(&stage)?;
        c.execute_batch(DDL)?;
        c.pragma_update(None, "application_id", APP)?;
        c.pragma_update(None, "user_version", 1)?;
        drop(c);
        std::fs::OpenOptions::new()
            .write(true)
            .open(&stage)?
            .sync_all()?;
        std::fs::rename(&stage, &path)?;
        Ok(())
    })();
    if stage.exists() {
        let _ = std::fs::remove_file(stage);
    }
    result
}
fn connection(root: &Path) -> Result<Connection> {
    files::database(&config::directory(root).join("peers.sqlite3"), APP, DDL)
}
pub fn invite(root: &Path) -> Result<Value> {
    let config = config::ensure_primary(root)?;
    let c = connection(root)?;
    c.execute(
        "DELETE FROM grants WHERE expires<? AND node_id IS NULL",
        [auth::now()],
    )?;
    let count: i64 = c.query_row("SELECT count(*) FROM grants", [], |r| r.get(0))?;
    if count >= 256 {
        return fail(429, "CLUSTER_JOIN_CAPACITY");
    }
    let key = uid()?;
    let ticket = credential()?;
    let expires = auth::now() + 1800;
    c.execute(
        "INSERT INTO grants(id,digest,expires) VALUES(?,?,?)",
        params![key, hash(&ticket), expires],
    )?;
    quote_diagnostics::event("cluster.invitation.created", json!({"grant_id":key}));
    Ok(
        json!({"format":"777-cluster-invitation-v1","cluster_id":config.cluster_id,"ledger_id":config.ledger_id,"primary":config.primary,"grant_id":key,"ticket":ticket,"expires":expires}),
    )
}
pub fn enroll(root: &Path, data: &Value) -> Result<Value> {
    crate::protocol::fields(
        data,
        &[
            "cluster_id",
            "ledger_id",
            "grant_id",
            "ticket",
            "node_id",
            "credential",
        ],
        &[],
    )?;
    let config = config::ensure_primary(root)?;
    if data["cluster_id"] != config.cluster_id || data["ledger_id"] != config.ledger_id {
        return fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    let text = |key: &str| -> Result<&str> {
        data[key]
            .as_str()
            .ok_or_else(|| Error::new(401, "CLUSTER_NOT_AUTHORIZED"))
    };
    let grant = text("grant_id")?;
    let node = text("node_id")?;
    let ticket = text("ticket")?;
    let secret = text("credential")?;
    id(grant)?;
    id(node)?;
    validate_secret(ticket)?;
    validate_secret(secret)?;
    let mut c = connection(root)?;
    let tx = c.transaction()?;
    type Grant = (String, i64, Option<String>, Option<String>);
    let row: Option<Grant> = tx
        .query_row(
            "SELECT digest,expires,node_id,credential FROM grants WHERE id=?",
            [grant],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;
    let (digest, expires, used, retained) =
        row.ok_or_else(|| Error::new(401, "CLUSTER_NOT_AUTHORIZED"))?;
    let fingerprint = hash(secret);
    if digest.as_bytes().ct_eq(hash(ticket).as_bytes()).unwrap_u8() != 1 {
        return fail(401, "CLUSTER_NOT_AUTHORIZED");
    }
    if let Some(used) = used {
        if used != node || retained.as_deref() != Some(fingerprint.as_str()) {
            return fail(401, "CLUSTER_INVITATION_ALREADY_USED");
        }
        let enabled: bool =
            tx.query_row("SELECT enabled FROM peers WHERE id=?", [node], |r| r.get(0))?;
        if !enabled {
            return fail(401, "CLUSTER_PEER_REVOKED");
        }
    } else {
        if expires <= auth::now() {
            return fail(401, "CLUSTER_INVITATION_EXPIRED");
        }
        let count: i64 = tx.query_row("SELECT count(*) FROM peers", [], |r| r.get(0))?;
        if count >= 128 {
            return fail(429, "CLUSTER_PEER_CAPACITY");
        }
        tx.execute(
            "INSERT INTO peers(id,credential,enabled) VALUES(?,?,1)",
            params![node, fingerprint],
        )?;
        tx.execute(
            "UPDATE grants SET node_id=?,credential=? WHERE id=?",
            params![node, fingerprint, grant],
        )?;
    }
    tx.commit()?;
    quote_diagnostics::event("cluster.peer.enrolled", json!({"node_id":node}));
    Ok(
        json!({"format":config::FORMAT,"cluster_id":config.cluster_id,"ledger_id":config.ledger_id,"node_id":node,"role":"replica","write_authority":"primary_only"}),
    )
}
pub fn authenticate(root: &Path, node: &str, secret: &str) -> Result<()> {
    id(node)?;
    validate_secret(secret)?;
    let c = connection(root)?;
    let row: Option<(String, bool)> = c
        .query_row(
            "SELECT credential,enabled FROM peers WHERE id=?",
            [node],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let (expected, enabled) = row.ok_or_else(|| Error::new(401, "CLUSTER_NOT_AUTHORIZED"))?;
    if expected
        .as_bytes()
        .ct_eq(hash(secret).as_bytes())
        .unwrap_u8()
        != 1
    {
        return fail(401, "CLUSTER_NOT_AUTHORIZED");
    }
    if !enabled {
        return fail(401, "CLUSTER_PEER_REVOKED");
    }
    Ok(())
}
pub fn acknowledge(root: &Path, node: &str, generation: u64, manifest: &str) -> Result<()> {
    let c = connection(root)?;
    c.execute("UPDATE peers SET generation=?,manifest=?,seen=?,fetch_until=0 WHERE id=? AND generation<=?",params![generation,manifest,auth::now(),node,generation])?;
    Ok(())
}
pub fn listing(root: &Path) -> Result<Value> {
    let c = connection(root)?;
    let mut st = c.prepare("SELECT id,enabled,generation,manifest,seen FROM peers ORDER BY id")?;
    let rows=st.query_map([],|r|Ok(json!({"node_id":r.get::<_,String>(0)?,"enabled":r.get::<_,bool>(1)?,"generation":r.get::<_,u64>(2)?,"manifest":r.get::<_,Option<String>>(3)?,"last_seen":r.get::<_,i64>(4)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
    Ok(json!(rows))
}
pub fn revoke(root: &Path, node: &str) -> Result<Value> {
    id(node)?;
    if connection(root)?.execute("UPDATE peers SET enabled=0 WHERE id=?", [node])? != 1 {
        return fail(404, "NOT_FOUND");
    }
    quote_diagnostics::event("cluster.peer.revoked", json!({"node_id":node}));
    Ok(json!({"revoked":true}))
}

/// A live transfer pins its immutable generation, even while orders keep arriving.
pub fn lease(root: &Path, node: &str, generation: u64, manifest: &str) -> Result<()> {
    connection(root)?.execute("UPDATE peers SET fetch_generation=?,fetch_manifest=?,fetch_until=? WHERE id=? AND enabled=1",params![generation,manifest,auth::now()+120,node])?;
    Ok(())
}
pub fn retained(root: &Path) -> Result<std::collections::BTreeSet<(u64, String)>> {
    let c = connection(root)?;
    let mut st=c.prepare("SELECT fetch_generation,fetch_manifest FROM peers WHERE enabled=1 AND fetch_until>? AND fetch_generation IS NOT NULL")?;
    let result = st
        .query_map([auth::now()], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<std::result::Result<_, _>>()?;
    Ok(result)
}

/// The auto-authorization intent is durable before this independently committed peer.
pub fn automatic_peer(root: &Path, node: &str, digest: &str) -> Result<()> {
    id(node)?;
    if !super::snapshot::hex(digest) {
        return fail(422, "AUTOMATIC_DIGEST_INVALID");
    }
    let mut c = connection(root)?;
    let tx = c.transaction()?;
    let row: Option<(String, bool)> = tx
        .query_row(
            "SELECT credential,enabled FROM peers WHERE id=?",
            [node],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((expected, enabled)) = row {
        if !enabled || expected != digest {
            return fail(409, "NODE_IDENTITY_CONFLICT");
        }
    } else {
        let count: i64 = tx.query_row("SELECT count(*) FROM peers", [], |r| r.get(0))?;
        if count >= 128 {
            return fail(429, "CLUSTER_PEER_CAPACITY");
        }
        tx.execute(
            "INSERT INTO peers(id,credential,enabled) VALUES(?,?,1)",
            params![node, digest],
        )?;
    }
    tx.commit()?;
    Ok(())
}

pub fn known_peer(root: &Path, node: &str) -> Result<bool> {
    id(node)?;
    Ok(connection(root)?.query_row(
        "SELECT EXISTS(SELECT 1 FROM peers WHERE id=?)",
        [node],
        |r| r.get(0),
    )?)
}
