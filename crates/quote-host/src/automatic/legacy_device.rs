//! Explicit old-device proof preserves order ownership without creating a new user.
use super::*;
pub fn adopt(
    s: &crate::service::Service,
    c: &Connection,
    data: &Value,
    device_secret: &str,
    package_secret: &str,
) -> Result<Value> {
    envelope(
        data,
        ENROLLMENT,
        &["package_id", "site_id", "ledger_id", "device_id"],
    )?;
    binding(c, data)?;
    let package = id(data, "package_id")?;
    let device = id(data, "device_id")?;
    let tx = c.unchecked_transaction()?;
    let old: Option<(String, String, bool)> = tx
        .query_row(
            "SELECT package_id,digest,enabled FROM automatic_devices WHERE id=?",
            [&device],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let m = packages::authenticate(&tx, &package, package_secret, old.is_some())?;
    if let Some((p, hash, on)) = old {
        if p != package || !on || !matches(&hash, device_secret) {
            return Err(denied());
        }
        if let Some(legacy) = &s.devices {
            legacy.retire_for_adoption(&device)?;
        }
        return Ok(json!({"device_id":device,"package_id":package}));
    }
    let legacy = s.devices.as_ref().ok_or_else(denied)?;
    let actor = legacy.prove(&s.auth, &device, device_secret, &m.delivery)?;
    let conflict: bool = tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM automatic_devices WHERE subject=?)",
        [&actor.subject],
        |r| r.get(0),
    )?;
    if conflict {
        return fail(409, "LEGACY_SUBJECT_ALREADY_ADOPTED");
    }
    capacity::device(&tx)?;
    tx.execute(
        "INSERT INTO automatic_devices VALUES(?,?,?,?,1,1)",
        params![device, actor.subject, package, digest(device_secret)?],
    )?;
    tx.execute(
        "UPDATE package_grants SET devices=devices+1 WHERE id=?",
        [&package],
    )?;
    audit(&tx, &device, "device.legacy_adopted", &package)?;
    tx.commit()?;
    legacy.retire_for_adoption(&device)?;
    Ok(json!({"device_id":device,"package_id":package}))
}
