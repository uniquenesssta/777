use super::*;
use crate::automatic::{self, sessions};
use quote_ledger::store::Actor;
use rusqlite::{params, OptionalExtension};
pub(super) struct Context {
    pub device: String,
    pub actor: Actor,
    pub package: String,
    pub capabilities: Vec<String>,
    pub site: String,
    pub device_epoch: i64,
    pub user_epoch: i64,
}
pub(super) fn load(i: &Intake, token: &str) -> Result<Context> {
    let c = i.auth.connection()?;
    let ctx = sessions::lookup(&c, token)?;
    if ctx.kind != "device" {
        return Err(Error::new(403, "OFFLINE_DEVICE_SESSION_REQUIRED"));
    }
    let m = ctx
        .manifest
        .ok_or_else(|| Error::new(403, "OFFLINE_DEVICE_SESSION_REQUIRED"))?;
    let (device_epoch,user_epoch):(i64,i64)=c.query_row("SELECT d.epoch,u.epoch FROM automatic_devices d JOIN users u ON u.id=d.subject WHERE d.id=?",params![ctx.id],|r|Ok((r.get(0)?,r.get(1)?)))?;
    automatic::permissions::require(&m.capabilities, "quote")?;
    if m.ledger_id != i.config["ledger_id"] || m.site_id != i.config["site_id"] {
        return Err(Error::new(409, "OFFLINE_SITE_CONFLICT"));
    }
    Ok(Context {
        device: ctx.id,
        actor: ctx
            .actor
            .ok_or_else(|| Error::new(403, "OFFLINE_DEVICE_SESSION_REQUIRED"))?,
        package: m.package_id,
        capabilities: m.capabilities,
        site: m.site_id,
        device_epoch,
        user_epoch,
    })
}
pub(super) fn device(i: &Intake, id: &str) -> Result<Context> {
    let c = i.auth.connection()?;
    let row:Option<(String,String,String,i64,i64)>=c.query_row("SELECT d.subject,u.role,d.package_id,d.epoch,u.epoch FROM automatic_devices d JOIN users u ON u.id=d.subject WHERE d.id=? AND d.enabled=1 AND u.enabled=1",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
    let (subject, role, package, device_epoch, user_epoch) =
        row.ok_or_else(|| Error::new(403, "OFFLINE_AUTHORIZATION_CHANGED"))?;
    let (manifest, status) = automatic::packages::get(&c, &package)?;
    if status == "revoked"
        || role
            != if manifest.delivery == "manager" {
                "admin"
            } else {
                "sales"
            }
    {
        return Err(Error::new(403, "OFFLINE_AUTHORIZATION_CHANGED"));
    }
    Ok(Context {
        device: id.into(),
        actor: Actor { subject, role },
        package,
        capabilities: manifest.capabilities,
        site: manifest.site_id,
        device_epoch,
        user_epoch,
    })
}
