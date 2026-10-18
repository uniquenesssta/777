use super::*;
use quote_ledger::store::Actor;
pub struct Context {
    pub id: String,
    pub kind: String,
    pub actor: Option<Actor>,
    pub manifest: Option<packages::Manifest>,
}
pub fn issuer_session(c: &Connection, data: &Value, secret: &str) -> Result<Value> {
    envelope(data, ISSUANCE, &["issuer_id"])?;
    let id = id(data, "issuer_id")?;
    let row: Option<(String, i64)> = c
        .query_row(
            "SELECT digest,epoch FROM issuers WHERE id=? AND enabled=1",
            [&id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let (expected, epoch) = row.ok_or_else(denied)?;
    if !matches(&expected, secret) {
        return Err(denied());
    }
    issue(c, "issuer", &id, epoch, 0)
}
pub fn issue(c: &Connection, kind: &str, id: &str, epoch: i64, user_epoch: i64) -> Result<Value> {
    let token = format!("a2.{}", secret()?);
    let at = auth::now();
    let tx = c.unchecked_transaction()?;
    tx.execute("DELETE FROM automatic_sessions WHERE expires<=?", [at])?;
    let count: i64 = tx.query_row(
        "SELECT count(*) FROM automatic_sessions WHERE principal_id=?",
        [id],
        |r| r.get(0),
    )?;
    if count >= 32 {
        return fail(429, "AUTOMATIC_SESSION_CAPACITY");
    }
    tx.execute(
        "INSERT INTO automatic_sessions VALUES(?,?,?,?,?,?)",
        params![store::hash(&token), kind, id, epoch, user_epoch, at + 900],
    )?;
    tx.commit()?;
    Ok(json!({"token":token,"expires":at+900}))
}
pub fn lookup(c: &Connection, token: &str) -> Result<Context> {
    if !token.starts_with("a2.") || token.len() != 46 {
        return Err(denied());
    }
    let row:Option<(String,String,i64,i64)>=c.query_row("SELECT kind,principal_id,epoch,user_epoch FROM automatic_sessions WHERE digest=? AND expires>?",params![store::hash(token),auth::now()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
    let (kind, id, epoch, user_epoch) = row.ok_or_else(denied)?;
    if kind == "issuer" {
        let valid: bool = c.query_row(
            "SELECT EXISTS(SELECT 1 FROM issuers WHERE id=? AND enabled=1 AND epoch=?)",
            params![id, epoch],
            |r| r.get(0),
        )?;
        if !valid {
            return Err(denied());
        }
        return Ok(Context {
            id,
            kind,
            actor: None,
            manifest: None,
        });
    }
    let row:Option<(String,String,String)>=c.query_row("SELECT d.subject,u.role,d.package_id FROM automatic_devices d JOIN users u ON u.id=d.subject WHERE d.id=? AND d.enabled=1 AND d.epoch=? AND u.enabled=1 AND u.epoch=?",params![id,epoch,user_epoch],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
    let (subject, role, package) = row.ok_or_else(denied)?;
    let (m, status) = packages::get(c, &package)?;
    if status == "revoked"
        || role
            != if m.delivery == "manager" {
                "admin"
            } else {
                "sales"
            }
    {
        return Err(denied());
    }
    Ok(Context {
        id,
        kind,
        actor: Some(Actor { subject, role }),
        manifest: Some(m),
    })
}
