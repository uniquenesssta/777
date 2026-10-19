use super::{context::Context, *};
use base64::{engine::general_purpose::STANDARD, Engine};
use ring::signature::{UnparsedPublicKey, ED25519};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::json;
pub(super) fn issue(i: &Intake, ctx: &Context, data: &Value) -> Result<Value> {
    crate::protocol::fields(data, &["protocol", "request_id"], &["new_stream"])?;
    if data.get("new_stream").is_some_and(|v| !v.is_boolean()) {
        return Err(Error::new(422, "OFFLINE_STREAM_INVALID"));
    }
    if data["protocol"] != FORMAT {
        return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
    }
    let request = envelope::uuid(&data["request_id"])?;
    let mut c = store::open(&i.ledger, true)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let old: Option<(String, String)> = tx
        .query_row(
            "SELECT fingerprint,lease_json FROM offline_leases WHERE device_id=? AND request_id=?",
            params![ctx.device, request],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((fingerprint, raw)) = old {
        if fingerprint != store::hash(store::encoded(data)) {
            return Err(Error::new(409, "OFFLINE_OPERATION_ID_CONFLICT"));
        }
        return Ok(serde_json::from_str(&raw)?);
    }
    super::capacity::disk(&i.root)?;
    let count: i64 = tx.query_row(
        "SELECT count(*) FROM offline_leases WHERE device_id=?",
        [&ctx.device],
        |r| r.get(0),
    )?;
    let total: i64 = tx.query_row("SELECT count(*) FROM offline_leases", [], |r| r.get(0))?;
    if count >= 4096 || total >= 100000 || storage::retained(&tx)? > 2147483648 - 65536 {
        return Err(Error::new(429, "OFFLINE_LEASE_CAPACITY"));
    }
    let existing: Option<String> = if data["new_stream"] == true {
        None
    } else {
        tx.query_row("SELECT s.stream_id FROM offline_streams s JOIN offline_leases l USING(stream_id) WHERE s.device_id=? AND s.package_id=? AND s.device_epoch=? AND s.user_epoch=? AND json_extract(l.lease_json,'$.body.epoch')=? ORDER BY s.created_at DESC,s.stream_id LIMIT 1",params![ctx.device,ctx.package,ctx.device_epoch,ctx.user_epoch,i.config["epoch"].as_str()],|r|r.get(0)).optional()?
    };
    let new_stream = existing.is_none();
    let stream = match existing {
        Some(id) => id,
        None => store::uid()?,
    };
    let lease = store::uid()?;
    let meta = store::verify(&tx)?;
    let price = meta["active_price_id"].clone();
    if price.is_null() {
        return Err(Error::new(409, "PRICES_NOT_PUBLISHED"));
    }
    let prices = store::load_prices(&tx, price.as_str().unwrap())?;
    // A digest of low-entropy private costs would still permit guessing them.
    // Bind the lease to the same public quotation projection for every role.
    let public_prices = crate::protocol::catalog(
        prices,
        &quote_ledger::store::Actor {
            subject: ctx.actor.subject.clone(),
            role: "sales".into(),
        },
    )?;
    let public_price_hash = store::hash(envelope::canonical(&public_prices)?);
    let body = json!({"format":LEASE,"lease_id":lease,"site_id":ctx.site,"ledger_id":i.config["ledger_id"],"device_id":ctx.device,"stream_id":stream,"subject":ctx.actor.subject,"package_id":ctx.package,"device_epoch":ctx.device_epoch.to_string(),"user_epoch":ctx.user_epoch.to_string(),"capabilities":ctx.capabilities,"price_version_id":price,"price_sha256":public_price_hash,"rule_version":quote_core::models::RULE_VERSION,"numeric_profile":quote_core::models::NUMERIC_PROFILE,"issued_at":crate::auth::now().to_string(),"expires_at":(crate::auth::now()+2592000).to_string(),"epoch":i.config["epoch"],"key_id":i.config["key_id"]});
    let signed = sign(&i.key, body)?;
    if new_stream {
        tx.execute(
            "INSERT INTO offline_streams VALUES(?,?,?,?,?,?,?)",
            params![
                stream,
                ctx.device,
                ctx.actor.subject,
                ctx.package,
                ctx.device_epoch,
                ctx.user_epoch,
                crate::auth::now()
            ],
        )?;
    }
    tx.execute(
        "INSERT INTO offline_leases VALUES(?,?,?,?,?,?)",
        params![
            lease,
            ctx.device,
            request,
            store::hash(store::encoded(data)),
            stream,
            store::encoded(&signed)
        ],
    )?;
    tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
    tx.commit()?;
    Ok(signed)
}
fn sign(key: &Ed25519KeyPair, body: Value) -> Result<Value> {
    let raw = envelope::canonical(&body)?;
    let mut input = format!("{LEASE}\n").into_bytes();
    input.extend(raw);
    Ok(
        json!({"body":body,"signature":STANDARD.encode(key.sign(&input).as_ref()),"public_key":STANDARD.encode(key.public_key().as_ref())}),
    )
}
pub(super) fn read(i: &Intake, c: &Connection, ctx: &Context, v: &Value) -> Result<Value> {
    let raw:Option<String>=c.query_row("SELECT lease_json FROM offline_leases WHERE lease_id=? AND device_id=? AND stream_id=?",params![v["lease_id"].as_str(),ctx.device,v["stream_id"].as_str()],|r|r.get(0)).optional()?;
    let signed: Value =
        serde_json::from_str(&raw.ok_or_else(|| Error::new(403, "OFFLINE_LEASE_UNKNOWN"))?)?;
    let b = &signed["body"];
    let keys: String = c.query_row(
        "SELECT public_keys_json FROM offline_meta WHERE id=1",
        [],
        |r| r.get(0),
    )?;
    let keys: Value = serde_json::from_str(&keys)?;
    let kid = b["key_id"]
        .as_str()
        .ok_or_else(|| Error::new(503, "OFFLINE_LEASE_INVALID"))?;
    let public = STANDARD
        .decode(
            keys[kid]
                .as_str()
                .ok_or_else(|| Error::new(503, "OFFLINE_LEASE_INVALID"))?,
        )
        .map_err(|_| Error::new(503, "OFFLINE_LEASE_INVALID"))?;
    let signature = STANDARD
        .decode(signed["signature"].as_str().unwrap_or(""))
        .map_err(|_| Error::new(503, "OFFLINE_LEASE_INVALID"))?;
    let mut input = format!("{LEASE}\n").into_bytes();
    input.extend(envelope::canonical(b)?);
    UnparsedPublicKey::new(&ED25519, public)
        .verify(&input, &signature)
        .map_err(|_| Error::new(503, "OFFLINE_LEASE_INVALID"))?;
    if b["subject"] != ctx.actor.subject
        || b["package_id"] != ctx.package
        || b["site_id"] != ctx.site
        || b["ledger_id"] != i.config["ledger_id"]
    {
        return Err(Error::new(403, "OFFLINE_LEASE_BINDING_CONFLICT"));
    }
    Ok(b.clone())
}
