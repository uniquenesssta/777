use super::*;
use quote_security::Connection as SiteConnection;
pub const PRIMARY: &str = "https://192.168.4.23:8477";
pub fn protocols() -> Value {
    json!({"issuance":ISSUANCE,"enrollment":ENROLLMENT,"scoped_auth":SCOPED_AUTH,"cluster_snapshot":crate::cluster::snapshot::FORMAT_V2})
}
pub fn profile(c: &Connection) -> Result<Value> {
    if !schema::enabled(c)? {
        return fail(426, "PROTOCOL_UPGRADE_REQUIRED");
    }
    let raw: String = c
        .query_row(
            "SELECT profile_json FROM site_binding WHERE id=1",
            [],
            |r| r.get(0),
        )
        .optional()?
        .ok_or_else(|| Error::new(409, "AUTOMATIC_SITE_NOT_BOUND"))?;
    Ok(serde_json::from_str(&raw)?)
}
pub fn install(
    c: &Connection,
    ledger: &str,
    connection: &SiteConnection,
    kit: &upgrade::Kit,
) -> Result<Value> {
    store::id(ledger)?;
    kit.validate()?;
    if connection.url.trim_end_matches('/') != PRIMARY {
        return fail(409, "AUTOMATIC_PRIMARY_ENDPOINT_CONFLICT");
    }
    quote_security::tls::configuration(connection).map_err(|e| Error::new(e.status, &e.code))?;
    let tx = c.unchecked_transaction()?;
    let old: Option<String> = tx
        .query_row(
            "SELECT profile_json FROM site_binding WHERE id=1",
            [],
            |r| r.get(0),
        )
        .optional()?;
    let p = if let Some(raw) = old {
        let p: Value = serde_json::from_str(&raw)?;
        if p["ledger_id"] != ledger
            || p["tls"]["certificate_sha256"] != connection.certificate_sha256
        {
            return fail(409, "AUTOMATIC_SITE_CONFLICT");
        }
        p
    } else {
        let p = json!({"format":"777-site-profile-v1","site_id":store::uid()?,"ledger_id":ledger,"primary_url":PRIMARY,"tls":{"certificate_pem":connection.certificate_pem,"certificate_sha256":connection.certificate_sha256},"trust_revision":1,"required_protocols":protocols()});
        tx.execute(
            "INSERT INTO site_binding VALUES(1,?,?,?)",
            params![p["site_id"].as_str(), ledger, store::encoded(&p)],
        )?;
        p
    };
    let old: Option<String> = tx
        .query_row(
            "SELECT digest FROM issuers WHERE id=?",
            [&kit.issuer_id],
            |r| r.get(0),
        )
        .optional()?;
    if let Some(digest) = old {
        if digest != kit.issuer_hash {
            return fail(409, "ISSUER_IDENTITY_CONFLICT");
        }
    } else {
        tx.execute(
            "INSERT INTO issuers VALUES(?,?,?,1,1)",
            params![
                kit.issuer_id,
                kit.issuer_hash,
                serde_json::to_string(&kit.capabilities)?
            ],
        )?;
    }
    let previous: Option<(String, String)> = tx
        .query_row(
            "SELECT issuer_id,pair_digest FROM upgrade_bindings WHERE id=?",
            [&kit.upgrade_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((issuer, hash)) = previous {
        if issuer != kit.issuer_id || hash != kit.pair_hash {
            return fail(409, "UPGRADE_BINDING_CONFLICT");
        }
    } else {
        tx.execute(
            "INSERT INTO upgrade_bindings VALUES(?,?,?,NULL,?,0)",
            params![
                kit.upgrade_id,
                kit.issuer_id,
                kit.pair_hash,
                kit.expires.min(auth::now() + 1800)
            ],
        )?;
        audit(&tx, "local-owner", "issuer.bound", &kit.issuer_id)?;
    }
    tx.commit()?;
    Ok(p)
}
pub fn pair(c: &Connection, data: &Value, token: &str) -> Result<Value> {
    envelope(data, ISSUANCE, &["upgrade_id", "challenge"])?;
    let id = id(data, "upgrade_id")?;
    let challenge = hex(data, "challenge")?;
    let tx = c.unchecked_transaction()?;
    let row:Option<(String,String,Option<String>,i64,bool)>=tx.query_row("SELECT issuer_id,pair_digest,challenge,expires,completed FROM upgrade_bindings WHERE id=?",[&id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
    let (issuer, hash, old, expires, completed) = row.ok_or_else(denied)?;
    if completed || expires <= auth::now() || !matches(&hash, token) {
        return Err(denied());
    }
    if old.is_some_and(|v| v != challenge) {
        return fail(409, "UPGRADE_CHALLENGE_CONFLICT");
    }
    tx.execute(
        "UPDATE upgrade_bindings SET challenge=? WHERE id=?",
        params![challenge, id],
    )?;
    tx.commit()?;
    Ok(json!({"upgrade_id":id,"issuer_id":issuer,"challenge":challenge,"profile":profile(c)?}))
}
pub fn confirm(c: &Connection, data: &Value, token: &str) -> Result<Value> {
    envelope(data, ISSUANCE, &["upgrade_id", "challenge"])?;
    let id = id(data, "upgrade_id")?;
    let challenge = hex(data, "challenge")?;
    let ctx = sessions::lookup(c, token)?;
    if ctx.kind != "issuer" {
        return Err(denied());
    }
    let tx = c.unchecked_transaction()?;
    let row: Option<(String, Option<String>, bool)> = tx
        .query_row(
            "SELECT issuer_id,challenge,completed FROM upgrade_bindings WHERE id=?",
            [&id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let (issuer, expected, _) = row.ok_or_else(denied)?;
    if issuer != ctx.id || expected.as_deref() != Some(&challenge) {
        return Err(denied());
    }
    tx.execute(
        "UPDATE upgrade_bindings SET completed=1,pair_digest='' WHERE id=?",
        [&id],
    )?;
    audit(&tx, &issuer, "issuer.confirmed", &id)?;
    tx.commit()?;
    Ok(json!({"confirmed":true}))
}
