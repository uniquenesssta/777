//! Node identities remain independent of desktop users and business sessions.
use super::*;
use std::path::Path;
pub fn permit(root: &Path, c: &Connection, data: &Value, token: &str) -> Result<Value> {
    let package = id(data, "package_id")?;
    let node = id(data, "node_id")?;
    let m = packages::authenticate(c, &package, token, true)?;
    if m.delivery != "manager" || !m.node_enrollment {
        return Err(denied());
    }
    let registered: bool = c.query_row(
        "SELECT EXISTS(SELECT 1 FROM automatic_nodes WHERE id=?)",
        [&node],
        |r| r.get(0),
    )?;
    if !registered && crate::cluster::membership::known_peer(root, &node)? {
        return fail(409, "NODE_LEGACY_PROOF_REQUIRED");
    }
    reserve(c, data, token)
}
fn reserve(c: &Connection, data: &Value, token: &str) -> Result<Value> {
    envelope(
        data,
        ENROLLMENT,
        &[
            "package_id",
            "site_id",
            "ledger_id",
            "node_id",
            "node_secret_hash",
        ],
    )?;
    binding(c, data)?;
    let package = id(data, "package_id")?;
    let node = id(data, "node_id")?;
    let hash = hex(data, "node_secret_hash")?;
    let tx = c.unchecked_transaction()?;
    let old: Option<(String, String, String)> = tx
        .query_row(
            "SELECT package_id,digest,state FROM automatic_nodes WHERE id=?",
            [&node],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let m = packages::authenticate(
        &tx,
        &package,
        token,
        old.as_ref().is_some_and(|v| v.2 == "active"),
    )?;
    if !m.node_enrollment || m.delivery != "manager" {
        return Err(denied());
    }
    if let Some((p, d, state)) = &old {
        if p != &package || d != &hash {
            return fail(409, "NODE_IDENTITY_CONFLICT");
        }
        if state == "revoked" {
            return Err(denied());
        }
    } else {
        let used: i64 = tx.query_row(
            "SELECT nodes FROM package_grants WHERE id=?",
            [&package],
            |r| r.get(0),
        )?;
        let total: i64 = tx.query_row("SELECT count(*) FROM automatic_nodes", [], |r| r.get(0))?;
        if used >= m.max_nodes || total >= 128 {
            return fail(403, "NODE_ENROLLMENT_CAPACITY");
        }
    }
    // Stable HMAC permits lost-response recovery without retaining plaintext.
    use base64::Engine;
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac = Hmac::<Sha256>::new_from_slice(token.as_bytes()).map_err(|_| denied())?;
    mac.update(format!("777-node-permit:{package}:{node}:{hash}").as_bytes());
    let ticket =
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    let expires = auth::now() + 1800;
    if old.is_none() {
        tx.execute(
            "INSERT INTO automatic_nodes VALUES(?,?,?,?,?,'reserved')",
            params![node, package, hash, digest(&ticket)?, expires],
        )?;
        tx.execute(
            "UPDATE package_grants SET nodes=nodes+1 WHERE id=?",
            [&package],
        )?;
        audit(&tx, &package, "node.permit", &node)?;
    } else {
        tx.execute(
            "UPDATE automatic_nodes SET permit_digest=?,permit_expires=? WHERE id=?",
            params![digest(&ticket)?, expires, node],
        )?;
    }
    tx.commit()?;
    Ok(json!({"node_id":node,"permit":ticket,"expires":expires}))
}
pub fn enroll(root: &Path, c: &Connection, data: &Value, token: &str) -> Result<Value> {
    envelope(
        data,
        ENROLLMENT,
        &["node_id", "node_secret_hash", "site_id", "ledger_id"],
    )?;
    binding(c, data)?;
    let node = id(data, "node_id")?;
    let hash = hex(data, "node_secret_hash")?;
    let row:Option<(String,String,String,i64,String)>=c.query_row("SELECT package_id,digest,permit_digest,permit_expires,state FROM automatic_nodes WHERE id=?",[&node],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
    let (package, expected, ticket, expires, state) = row.ok_or_else(denied)?;
    let (_, status) = packages::get(c, &package)?;
    if expected != hash
        || !matches(&ticket, token)
        || status == "revoked"
        || state == "revoked"
        || state != "active" && expires <= auth::now()
    {
        return Err(denied());
    }
    let config = crate::cluster::config::ensure_primary(root)?;
    // A peer row alone never opens snapshot access before activation commits.
    crate::cluster::membership::automatic_peer(root, &node, &hash)?;
    let tx = c.unchecked_transaction()?;
    if tx.execute(
        "UPDATE automatic_nodes SET state='active' WHERE id=? AND state='reserved'",
        [&node],
    )? == 1
    {
        audit(&tx, &package, "node.enrolled", &node)?;
    }
    tx.commit()?;
    Ok(
        json!({"node_id":node,"cluster_id":config.cluster_id,"ledger_id":config.ledger_id,"primary":config.primary,"role":"replica","write_authority":"primary_only","snapshot_protocol":crate::cluster::snapshot::FORMAT_V2}),
    )
}
pub fn authorize(c: &Connection, node: &str) -> Result<()> {
    if !schema::enabled(c)? {
        return Ok(());
    }
    let row:Option<(String,String)>=c.query_row("SELECT n.state,p.status FROM automatic_nodes n JOIN package_grants p ON p.id=n.package_id WHERE n.id=?",[node],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
    if row.is_some_and(|(state, status)| state != "active" || status == "revoked") {
        return Err(denied());
    }
    Ok(())
}
pub fn upgrade(c: &Connection, data: &Value, secret: &str, package_token: &str) -> Result<Value> {
    let request = envelope(data, ENROLLMENT, &["node_id", "package_id"])?;
    let node = id(data, "node_id")?;
    let next = id(data, "package_id")?;
    let tx = c.unchecked_transaction()?;
    let old: Option<(String, String, String)> = tx
        .query_row(
            "SELECT package_id,digest,state FROM automatic_nodes WHERE id=?",
            [&node],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let (old, expected, state) = old.ok_or_else(denied)?;
    if state != "active" || !matches(&expected, secret) || packages::get(&tx, &old)?.1 == "revoked"
    {
        return Err(denied());
    }
    let m = packages::authenticate(&tx, &next, package_token, true)?;
    if !m.node_enrollment {
        return Err(denied());
    }
    let scope = format!("node.upgrade:{node}");
    if let Some(v) = receipt(&tx, &scope, &request, data)? {
        return Ok(v);
    }
    if old != next {
        packages::authenticate(&tx, &next, package_token, false)?;
        let used: i64 = tx.query_row(
            "SELECT nodes FROM package_grants WHERE id=?",
            [&next],
            |r| r.get(0),
        )?;
        if used >= m.max_nodes {
            return Err(denied());
        }
        tx.execute(
            "UPDATE automatic_nodes SET package_id=? WHERE id=?",
            params![next, node],
        )?;
        tx.execute(
            "UPDATE package_grants SET nodes=nodes+1 WHERE id=?",
            [&next],
        )?;
    }
    let v = json!({"node_id":node,"package_id":next});
    remember(&tx, &scope, &request, data, &v)?;
    audit(&tx, &node, "node.upgraded", &next)?;
    tx.commit()?;
    Ok(v)
}
/// Adopt an existing same-ledger peer only with proof of its original secret.
pub fn adopt(
    root: &Path,
    c: &Connection,
    data: &Value,
    node_secret: &str,
    package_secret: &str,
) -> Result<Value> {
    envelope(
        data,
        ENROLLMENT,
        &[
            "package_id",
            "site_id",
            "ledger_id",
            "node_id",
            "node_secret_hash",
        ],
    )?;
    binding(c, data)?;
    let node = id(data, "node_id")?;
    crate::cluster::membership::authenticate(root, &node, node_secret)?;
    if hex(data, "node_secret_hash")? != digest(node_secret)? {
        return fail(409, "NODE_IDENTITY_CONFLICT");
    }
    let permit = reserve(c, data, package_secret)?;
    let mut join = data.clone();
    join.as_object_mut().unwrap().remove("package_id");
    enroll(
        root,
        c,
        &join,
        permit["permit"].as_str().ok_or_else(denied)?,
    )
}
