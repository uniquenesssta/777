use super::*;
use serde::{Deserialize, Serialize};
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub package_id: String,
    pub issuer_id: String,
    pub site_id: String,
    pub ledger_id: String,
    pub trust_revision: i64,
    pub delivery: String,
    pub capabilities: Vec<String>,
    pub node_enrollment: bool,
    pub release_version: String,
    pub artifact_sha256: String,
    pub protocols: Value,
    pub enroll_before: i64,
    pub max_devices: i64,
    pub max_nodes: i64,
}
impl Manifest {
    pub fn validate(&self, c: &Connection) -> Result<()> {
        for value in [
            &self.package_id,
            &self.issuer_id,
            &self.site_id,
            &self.ledger_id,
        ] {
            store::id(value)?;
        }
        permissions::validate(&self.delivery, &self.capabilities)?;
        let p = trust::profile(c)?;
        if self.format != "777-package-manifest-v1" || self.protocols != trust::protocols() {
            return fail(426, "PROTOCOL_UPGRADE_REQUIRED");
        }
        if self.site_id != p["site_id"]
            || self.ledger_id != p["ledger_id"]
            || self.trust_revision != p["trust_revision"]
        {
            return fail(409, "AUTOMATIC_SITE_CONFLICT");
        }
        if !crate::cluster::snapshot::hex(&self.artifact_sha256)
            || self.release_version.is_empty()
            || self.release_version.len() > 64
            || self.release_version.chars().any(char::is_control)
            || !(1..=4096).contains(&self.max_devices)
            || !(0..=128).contains(&self.max_nodes)
            || self.delivery == "sales" && (self.node_enrollment || self.max_nodes != 0)
            || self.node_enrollment != (self.max_nodes > 0)
        {
            return fail(422, "PACKAGE_MANIFEST_INVALID");
        }
        Ok(())
    }
}
pub fn get(c: &Connection, id: &str) -> Result<(Manifest, String)> {
    let row: Option<(String, String)> = c
        .query_row(
            "SELECT manifest_json,status FROM package_grants WHERE id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let (raw, status) = row.ok_or_else(denied)?;
    Ok((serde_json::from_str(&raw)?, status))
}
pub fn authenticate(c: &Connection, id: &str, token: &str, existing: bool) -> Result<Manifest> {
    let expected: String = c
        .query_row("SELECT digest FROM package_grants WHERE id=?", [id], |r| {
            r.get(0)
        })
        .optional()?
        .ok_or_else(denied)?;
    if !matches(&expected, token) {
        return Err(denied());
    }
    let (m, status) = get(c, id)?;
    if status == "revoked" || !existing && (status != "active" || m.enroll_before <= auth::now()) {
        return Err(denied());
    }
    Ok(m)
}
pub fn create(c: &Connection, issuer: &str, data: &Value) -> Result<Value> {
    let request = envelope(data, ISSUANCE, &["manifest", "secret_hash"])?;
    let m: Manifest = serde_json::from_value(data["manifest"].clone())?;
    m.validate(c)?;
    if m.issuer_id != issuer {
        return Err(denied());
    }
    let ceiling: String = c.query_row(
        "SELECT capabilities_json FROM issuers WHERE id=? AND enabled=1",
        [issuer],
        |r| r.get(0),
    )?;
    let ceiling: Vec<String> = serde_json::from_str(&ceiling)?;
    if m.capabilities.iter().any(|v| !ceiling.contains(v)) {
        return Err(denied());
    }
    let hash = hex(data, "secret_hash")?;
    let scope = format!("issue:{issuer}");
    let tx = c.unchecked_transaction()?;
    if receipt(&tx, &scope, &request, data)?.is_some() {
        return listing(&tx, issuer, &m.package_id);
    }
    let existing: Option<(String, String)> = tx
        .query_row(
            "SELECT manifest_json,digest FROM package_grants WHERE id=?",
            [&m.package_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let raw = store::encoded(&data["manifest"]);
    if let Some((old, digest)) = existing {
        if old != raw || digest != hash {
            return fail(409, "PACKAGE_ID_CONFLICT");
        }
    } else {
        if m.enroll_before <= auth::now() || m.enroll_before > auth::now() + 366 * 86400 {
            return fail(422, "PACKAGE_EXPIRY_INVALID");
        }
        let count: i64 = tx.query_row("SELECT count(*) FROM package_grants", [], |r| r.get(0))?;
        if count >= 4096 {
            return fail(429, "PACKAGE_CAPACITY");
        }
        tx.execute("INSERT INTO package_grants(id,issuer_id,digest,manifest_json,status) VALUES(?,?,?,?,'active')",params![m.package_id,issuer,hash,raw])?;
        audit(&tx, issuer, "package.created", &m.package_id)?;
    }
    let v = listing(&tx, issuer, &m.package_id)?;
    remember(&tx, &scope, &request, data, &v)?;
    tx.commit()?;
    Ok(v)
}
pub fn listing(c: &Connection, issuer: &str, id: &str) -> Result<Value> {
    store::id(id)?;
    let (raw,status,devices,nodes)=c.query_row("SELECT manifest_json,status,devices,nodes FROM package_grants WHERE id=? AND issuer_id=?",params![id,issuer],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?,r.get::<_,i64>(3)?))).optional()?.ok_or_else(denied)?;
    Ok(
        json!({"manifest":serde_json::from_str::<Value>(&raw)?,"status":status,"devices":devices,"nodes":nodes}),
    )
}
pub fn close(c: &Connection, issuer: &str, id: &str, data: &Value, revoke: bool) -> Result<Value> {
    let request = envelope(data, ISSUANCE, &[])?;
    store::id(id)?;
    let scope = format!("package:{id}:{}", if revoke { "revoke" } else { "close" });
    let tx = c.unchecked_transaction()?;
    let old = listing(&tx, issuer, id)?;
    if let Some(v) = receipt(&tx, &scope, &request, data)? {
        return Ok(v);
    }
    let status = if revoke || old["status"] == "revoked" {
        "revoked"
    } else {
        "closed"
    };
    tx.execute(
        "UPDATE package_grants SET status=? WHERE id=?",
        params![status, id],
    )?;
    audit(&tx, issuer, &scope, id)?;
    let v = json!({"package_id":id,"status":status});
    remember(&tx, &scope, &request, data, &v)?;
    tx.commit()?;
    Ok(v)
}
