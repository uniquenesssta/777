//! Authenticated cursors bind the ledger recovery epoch and current permissions.
use super::super::{context::Context, Intake};
use crate::{Error, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quote_ledger::store;
use ring::signature::{KeyPair, UnparsedPublicKey, ED25519};
use serde_json::{json, Value};
fn binding(i: &Intake, ctx: &Context) -> Value {
    json!({"epoch":i.config["epoch"],"device":ctx.device,"subject":ctx.actor.subject,"package":ctx.package,"device_epoch":ctx.device_epoch,"user_epoch":ctx.user_epoch,"capabilities":ctx.capabilities})
}
pub(super) fn encode(i: &Intake, ctx: &Context, after: i64) -> String {
    let body = store::encoded(
        &json!({"format":"777-offline-feed-v1","binding":binding(i,ctx),"after":after}),
    );
    format!(
        "{}.{}",
        URL_SAFE_NO_PAD.encode(&body),
        URL_SAFE_NO_PAD.encode(i.key.sign(body.as_bytes()).as_ref())
    )
}
pub(super) fn decode(i: &Intake, ctx: &Context, v: &Value) -> Result<i64> {
    if v.is_null() {
        return Ok(0);
    }
    let invalid = || Error::new(409, "OFFLINE_CURSOR_REBUILD_REQUIRED");
    let s = v.as_str().filter(|s| s.len() <= 4096).ok_or_else(invalid)?;
    let (body, sig) = s.split_once('.').ok_or_else(invalid)?;
    let body = URL_SAFE_NO_PAD.decode(body).map_err(|_| invalid())?;
    let sig = URL_SAFE_NO_PAD.decode(sig).map_err(|_| invalid())?;
    UnparsedPublicKey::new(&ED25519, i.key.public_key().as_ref())
        .verify(&body, &sig)
        .map_err(|_| invalid())?;
    let data: Value = serde_json::from_slice(&body).map_err(|_| invalid())?;
    if data["format"] != "777-offline-feed-v1" || data["binding"] != binding(i, ctx) {
        return Err(invalid());
    }
    data["after"]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or_else(invalid)
}
