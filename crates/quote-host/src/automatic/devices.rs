use super::*;
pub fn enroll(c: &Connection, data: &Value, token: &str) -> Result<Value> {
    let request = envelope(
        data,
        ENROLLMENT,
        &[
            "package_id",
            "site_id",
            "ledger_id",
            "device_id",
            "device_secret_hash",
        ],
    )?;
    binding(c, data)?;
    let package = id(data, "package_id")?;
    let device = id(data, "device_id")?;
    let hash = hex(data, "device_secret_hash")?;
    let tx = c.unchecked_transaction()?;
    let old: Option<(String, String, String, bool)> = tx
        .query_row(
            "SELECT subject,package_id,digest,enabled FROM automatic_devices WHERE id=?",
            [&device],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;
    let m = packages::authenticate(&tx, &package, token, old.is_some())?;
    if let Some((subject, old_package, expected, on)) = old {
        if !on {
            return Err(denied());
        }
        if old_package != package || expected != hash {
            return fail(409, "DEVICE_IDENTITY_CONFLICT");
        }
        let enabled: bool =
            tx.query_row("SELECT enabled FROM users WHERE id=?", [&subject], |r| {
                r.get(0)
            })?;
        if !enabled {
            return Err(denied());
        }
        return Ok(
            json!({"device_id":device,"subject":subject,"delivery":m.delivery,"capabilities":m.capabilities,"epoch":device_epoch(&tx,&device)?}),
        );
    }
    if let Some(v) = receipt(&tx, &format!("enroll:{device}"), &request, data)? {
        return Ok(v);
    }
    let used: i64 = tx.query_row(
        "SELECT devices FROM package_grants WHERE id=?",
        [&package],
        |r| r.get(0),
    )?;
    let total: i64 = tx.query_row("SELECT count(*) FROM automatic_devices", [], |r| r.get(0))?;
    if used >= m.max_devices || total >= 4096 {
        return fail(403, "DEVICE_ENROLLMENT_CAPACITY");
    }
    let subject = store::uid()?;
    let role = if m.delivery == "manager" {
        "admin"
    } else {
        "sales"
    };
    let salt = auth::random::<16>()?;
    tx.execute(
        "INSERT INTO users VALUES(?,?,?,?,?,1,1)",
        params![
            subject,
            format!("device-{device}"),
            role,
            salt.as_slice(),
            auth::random::<32>()?.as_slice()
        ],
    )?;
    tx.execute(
        "INSERT INTO principal_modes VALUES(?,'device_only')",
        [&subject],
    )?;
    tx.execute(
        "INSERT INTO automatic_devices VALUES(?,?,?,?,1,1)",
        params![device, subject, package, hash],
    )?;
    tx.execute(
        "UPDATE package_grants SET devices=devices+1 WHERE id=?",
        [&package],
    )?;
    let v = json!({"device_id":device,"subject":subject,"delivery":m.delivery,"capabilities":m.capabilities,"epoch":1});
    remember(&tx, &format!("enroll:{device}"), &request, data, &v)?;
    audit(&tx, &package, "device.enrolled", &device)?;
    tx.commit()?;
    Ok(v)
}
fn device_epoch(c: &Connection, id: &str) -> Result<i64> {
    Ok(c.query_row(
        "SELECT epoch FROM automatic_devices WHERE id=?",
        [id],
        |r| r.get(0),
    )?)
}
pub fn session(c: &Connection, data: &Value, token: &str) -> Result<Value> {
    envelope(data, SCOPED_AUTH, &["device_id"])?;
    let device = id(data, "device_id")?;
    let row:Option<(String,String,i64,i64,String,String)>=c.query_row("SELECT d.digest,d.subject,d.epoch,u.epoch,d.package_id,u.role FROM automatic_devices d JOIN users u ON u.id=d.subject WHERE d.id=? AND d.enabled=1 AND u.enabled=1",[&device],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional()?;
    let (expected, subject, epoch, user_epoch, package, role) = row.ok_or_else(denied)?;
    if !matches(&expected, token) {
        return Err(denied());
    }
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
    let mut v = sessions::issue(c, "device", &device, epoch, user_epoch)?;
    v["subject"] = json!(subject);
    v["delivery"] = json!(m.delivery);
    v["capabilities"] = json!(m.capabilities);
    Ok(v)
}
pub fn upgrade(c: &Connection, data: &Value, token: &str, package_token: &str) -> Result<Value> {
    let request = envelope(data, ENROLLMENT, &["package_id"])?;
    let next = id(data, "package_id")?;
    let ctx = sessions::lookup(c, token)?;
    if ctx.kind != "device" {
        return Err(denied());
    }
    let tx = c.unchecked_transaction()?;
    let m = packages::authenticate(&tx, &next, package_token, true)?;
    let scope = format!("device.upgrade:{}", ctx.id);
    if let Some(v) = receipt(&tx, &scope, &request, data)? {
        return Ok(v);
    }
    if m.delivery != ctx.manifest.as_ref().unwrap().delivery {
        return fail(409, "DEVICE_DELIVERY_CONFLICT");
    }
    if m.package_id == ctx.manifest.as_ref().unwrap().package_id {
        return Ok(json!({"device_id":ctx.id,"package_id":next}));
    }
    packages::authenticate(&tx, &next, package_token, false)?;
    let used: i64 = tx.query_row(
        "SELECT devices FROM package_grants WHERE id=?",
        [&next],
        |r| r.get(0),
    )?;
    if used >= m.max_devices {
        return fail(403, "DEVICE_ENROLLMENT_CAPACITY");
    }
    tx.execute(
        "UPDATE automatic_devices SET package_id=?,epoch=epoch+1 WHERE id=?",
        params![next, ctx.id],
    )?;
    tx.execute(
        "UPDATE package_grants SET devices=devices+1 WHERE id=?",
        [&next],
    )?;
    tx.execute(
        "DELETE FROM automatic_sessions WHERE kind='device' AND principal_id=?",
        [&ctx.id],
    )?;
    let v = json!({"device_id":ctx.id,"package_id":next});
    remember(&tx, &scope, &request, data, &v)?;
    audit(&tx, &ctx.id, "device.upgraded", &next)?;
    tx.commit()?;
    Ok(v)
}
pub fn revoke(c: &Connection, id: &str) -> Result<Value> {
    store::id(id)?;
    let tx = c.unchecked_transaction()?;
    if tx.execute(
        "UPDATE automatic_devices SET enabled=0,epoch=epoch+1 WHERE id=?",
        [id],
    )? != 1
    {
        return fail(404, "NOT_FOUND");
    }
    tx.execute(
        "DELETE FROM automatic_sessions WHERE kind='device' AND principal_id=?",
        [id],
    )?;
    audit(&tx, "local-owner", "device.revoked", id)?;
    tx.commit()?;
    Ok(json!({"revoked":true}))
}
