use super::super::Intake;
use crate::{files, Error, Result};
use quote_ledger::store::Actor;
pub(super) fn reviewer(i: &Intake, token: &str) -> Result<Actor> {
    if token.contains('.') {
        return Err(Error::new(403, "OFFLINE_REVIEWER_REQUIRED"));
    }
    let actor = i.auth.authenticate(token)?;
    actor.admin()?;
    let path = i.root.join("private/offline-reviewers.json");
    if !path.try_exists()? {
        return Err(Error::new(403, "OFFLINE_REVIEWER_REQUIRED"));
    }
    let grants = files::read_json(&path)?;
    let epoch: i64 = i.auth.connection()?.query_row(
        "SELECT epoch FROM users WHERE id=? AND enabled=1 AND role='admin'",
        [&actor.subject],
        |r| r.get(0),
    )?;
    if grants["format"] != "777-offline-reviewers-v1"
        || grants["epoch"] != i.config["epoch"]
        || grants["ledger_id"] != i.config["ledger_id"]
        || grants["reviewers"][&actor.subject].as_i64() != Some(epoch)
    {
        return Err(Error::new(403, "OFFLINE_REVIEWER_REQUIRED"));
    }
    Ok(actor)
}
