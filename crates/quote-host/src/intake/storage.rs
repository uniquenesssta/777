use super::{context::Context, *};
use crate::automatic::permissions;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::json;
pub(super) fn retained(c: &Connection) -> Result<i64> {
    Ok(c.query_row("SELECT (SELECT coalesce(sum(length(CAST(operation_json AS BLOB))),0) FROM offline_operations)+(SELECT coalesce(sum(length(CAST(operation_json AS BLOB))),0) FROM offline_collisions)+(SELECT coalesce(sum(length(CAST(lease_json AS BLOB))),0) FROM offline_leases)+(SELECT coalesce(sum(length(CAST(base_json AS BLOB))+length(CAST(current_json AS BLOB))+length(CAST(candidate_json AS BLOB))),0) FROM offline_conflicts)+(SELECT coalesce(sum(length(CAST(decision_json AS BLOB))),0) FROM offline_resolutions)",[],|r|r.get(0))?)
}
pub(super) fn receipt(c: &Connection, ctx: &Context, id: &str) -> Result<Value> {
    let row:Option<(String,String,i64)>=c.query_row("SELECT o.content_sha256,s.state,o.received_at FROM offline_operations o JOIN offline_states s USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE o.operation_id=? AND d.device_id=? AND d.subject_id=?",params![id,ctx.device,ctx.actor.subject],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
    match row {
        Some((digest, state, at)) => {
            let mut receipt = json!({"operation_id":id,"content_sha256":digest,"state":state,"received_at":at.to_string(),"applied":state=="applied"});
            let resolved:Option<(String,String)>=c.query_row("SELECT d.decision_json,r.result_json FROM offline_resolutions d JOIN requests r ON r.request_id=d.resolution_operation_id WHERE d.operation_id=?",[id],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
            let result = if let Some((decision, raw)) = resolved {
                let decision: Value = serde_json::from_str(&decision)?;
                receipt["resolution"] = decision["disposition"].clone();
                Some(raw)
            } else {
                c.query_row("SELECT r.result_json FROM offline_states s JOIN requests r ON r.request_id=s.applied_request_id WHERE s.operation_id=?",[id],|r|r.get::<_,String>(0)).optional()?
            };
            if let Some(raw) = result {
                let mut result: Value = serde_json::from_str(&raw)?;
                if !ctx.capabilities.iter().any(|c| c == "finance") {
                    permissions::redact(&mut result)
                }
                for key in ["revision", "ledger_revision"] {
                    if let Some(n) = result[key].as_i64() {
                        result[key] = json!(n.to_string());
                    }
                }
                receipt["result"] = result;
            }
            Ok(receipt)
        }
        None => Ok(json!({"operation_id":id,"state":"not_found"})),
    }
}
fn binding(i: &Intake, ctx: &Context, v: &Value) -> Result<()> {
    if v["site_id"] != ctx.site
        || v["ledger_id"] != i.config["ledger_id"]
        || v["device_id"] != ctx.device
    {
        return Err(Error::new(409, "OFFLINE_SITE_OR_DEVICE_CONFLICT"));
    }
    if (ctx.actor.role == "sales" || v["kind"] == "create") && v["owner_id"] != ctx.actor.subject {
        return Err(Error::new(403, "FORBIDDEN"));
    }
    Ok(())
}
pub(super) fn reason(i: &Intake, ctx: &Context, v: &Value, lease: &Value) -> Option<&'static str> {
    if lease["epoch"] != i.config["epoch"] {
        return Some("RESTORED_REQUIRES_REVIEW");
    }
    if lease["device_epoch"].as_str() != Some(ctx.device_epoch.to_string().as_str())
        || lease["user_epoch"].as_str() != Some(ctx.user_epoch.to_string().as_str())
    {
        return Some("AUTHORIZATION_CHANGED");
    }
    if lease["expires_at"]
        .as_str()
        .and_then(|s| s.parse::<i64>().ok())
        .is_none_or(|t| t <= crate::auth::now())
    {
        return Some("OFFLINE_LEASE_EXPIRED");
    }
    if v["rule_version"] != quote_core::models::RULE_VERSION
        || v["numeric_profile"] != quote_core::models::NUMERIC_PROFILE
    {
        return Some("BUSINESS_RULE_CHANGED");
    }
    let required = if v["kind"] == "create" {
        "quote"
    } else {
        "edit_orders"
    };
    if permissions::require(&ctx.capabilities, required).is_err()
        || !lease["capabilities"]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v == required))
    {
        return Some("PACKAGE_PERMISSION_CHANGED");
    }
    if v["kind"] == "create"
        && v["payload"]["snapshot"]["price_version_id"] != lease["price_version_id"]
    {
        return Some("OFFLINE_PRICE_NOT_AUTHORIZED");
    }
    None
}
pub(super) fn dependency(c: &Connection, v: &Value, batch: &[Value]) -> Result<()> {
    let mut current = v.clone();
    let mut seen = std::collections::HashSet::new();
    seen.insert(v["operation_id"].as_str().unwrap().to_owned());
    for _ in 0..1024 {
        let Some(id) = current["base"]["previous_operation_id"].as_str() else {
            return Ok(());
        };
        if !seen.insert(id.into()) {
            return Err(Error::new(422, "OFFLINE_DEPENDENCY_CYCLE"));
        }
        let previous = if let Some(p) = batch.iter().find(|p| p["operation_id"] == id) {
            Some(p.clone())
        } else {
            c.query_row("SELECT o.stream_id,d.device_id,o.order_id,o.owner_id,o.previous_operation_id FROM offline_operations o JOIN offline_streams d USING(stream_id) WHERE o.operation_id=?",[id],|r|Ok(json!({"stream_id":r.get::<_,String>(0)?,"device_id":r.get::<_,String>(1)?,"order_id":r.get::<_,String>(2)?,"owner_id":r.get::<_,String>(3)?,"base":{"previous_operation_id":r.get::<_,Option<String>>(4)?}}))).optional()?
        };
        let Some(previous) = previous else {
            return Ok(());
        };
        if ["stream_id", "device_id", "order_id", "owner_id"]
            .iter()
            .any(|k| previous[*k] != v[*k])
        {
            return Err(Error::new(409, "OFFLINE_DEPENDENCY_BINDING_CONFLICT"));
        }
        current = previous;
    }
    Err(Error::new(429, "OFFLINE_DEPENDENCY_DEPTH"))
}
pub(super) fn receive(i: &Intake, ctx: &Context, ops: &[Value]) -> Result<Value> {
    let result = receive_batch(i, ctx, ops);
    if result
        .as_ref()
        .is_err_and(|e| e.code == "OFFLINE_OPERATION_ID_CONFLICT")
    {
        // Batch transaction has rolled back; collision evidence is independently bounded.
        let _ = collision(i, ctx, ops);
    }
    result
}
fn collision(i: &Intake, ctx: &Context, ops: &[Value]) -> Result<()> {
    let mut c = store::open(&i.ledger, true)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let total: i64 = tx.query_row("SELECT count(*) FROM offline_collisions", [], |r| r.get(0))?;
    let device: i64 = tx.query_row(
        "SELECT count(*) FROM offline_collisions WHERE device_id=?",
        [&ctx.device],
        |r| r.get(0),
    )?;
    if total + ops.len() as i64 > 4096
        || device + ops.len() as i64 > 1024
        || retained(&tx)?
            + ops
                .iter()
                .map(|v| store::encoded(v).len() as i64)
                .sum::<i64>()
            > 2147483648
    {
        return Ok(());
    }
    for v in ops {
        if envelope::validate(v).is_err() || binding(i, ctx, v).is_err() {
            continue;
        }
        let n=tx.execute("INSERT OR IGNORE INTO offline_collisions(device_id,operation_id,content_sha256,operation_json,received_at) VALUES(?,?,?,?,?)",params![ctx.device,v["operation_id"].as_str(),v["content_sha256"].as_str(),store::encoded(v),crate::auth::now()])?;
        if n > 0 {
            tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
        }
    }
    tx.commit()?;
    Ok(())
}
fn receive_batch(i: &Intake, ctx: &Context, ops: &[Value]) -> Result<Value> {
    let mut c = store::open(&i.ledger, true)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let mut pending = Vec::new();
    let mut seen = std::collections::HashMap::new();
    let mut sequences = std::collections::HashSet::new();
    for v in ops {
        envelope::validate(v)?;
        binding(i, ctx, v)?;
        let id = v["operation_id"].as_str().unwrap();
        let sha = v["content_sha256"].as_str().unwrap();
        if let Some(old) = seen.insert(id, sha) {
            if old != sha {
                return Err(Error::new(409, "OFFLINE_OPERATION_ID_CONFLICT"));
            }
            continue;
        }
        if !sequences.insert((
            v["stream_id"].as_str(),
            envelope::sequence(&v["device_sequence"])?,
        )) {
            return Err(Error::new(409, "OFFLINE_OPERATION_ID_CONFLICT"));
        }
        let old:Option<(String,String,String)>=tx.query_row("SELECT o.content_sha256,d.device_id,d.subject_id FROM offline_operations o JOIN offline_streams d USING(stream_id) WHERE o.operation_id=?",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        if let Some((digest, device, subject)) = old {
            if digest != sha || device != ctx.device || subject != ctx.actor.subject {
                return Err(Error::new(409, "OFFLINE_OPERATION_ID_CONFLICT"));
            }
            continue;
        }
        if i.outputs
            .as_ref()
            .map(|o| o.has_request(id))
            .transpose()?
            .unwrap_or(false)
        {
            return Err(Error::new(409, "OFFLINE_OPERATION_ID_CONFLICT"));
        }
        if tx.query_row("SELECT EXISTS(SELECT 1 FROM requests WHERE request_id=?)",[id],|r|r.get::<_,bool>(0))?||tx.query_row("SELECT EXISTS(SELECT 1 FROM offline_operations WHERE stream_id=? AND device_sequence=?)",params![v["stream_id"].as_str(),envelope::sequence(&v["device_sequence"])?],|r|r.get::<_,bool>(0))?{return Err(Error::new(409,"OFFLINE_OPERATION_ID_CONFLICT"));}
        let lease = leases::read(i, &tx, ctx, v)?;
        dependency(&tx, v, ops)?;
        // Check existing ownership before accepting edits of central orders.
        let owner: Option<String> = tx
            .query_row(
                "SELECT owner_id FROM orders WHERE order_id=?",
                [v["order_id"].as_str()],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(owner) = owner {
            if v["owner_id"] != owner || ctx.actor.role == "sales" && owner != ctx.actor.subject {
                return Err(Error::new(403, "FORBIDDEN"));
            }
        }
        pending.push((v, reason(i, ctx, v, &lease)));
    }
    if !pending.is_empty() {
        capacity::disk(&i.root)?;
        let total: i64 = tx.query_row(
            "SELECT count(*) FROM offline_states WHERE state IN ('received','waiting_dependency')",
            [],
            |r| r.get(0),
        )?;
        let device:i64=tx.query_row("SELECT count(*) FROM offline_operations o JOIN offline_states s USING(operation_id) JOIN offline_streams d USING(stream_id) WHERE d.device_id=? AND s.state IN ('received','waiting_dependency')",[&ctx.device],|r|r.get(0))?;
        let bytes = retained(&tx)?;
        let extra: usize = pending.iter().map(|(v, _)| store::encoded(v).len()).sum();
        if total + pending.len() as i64 > 100000
            || device + pending.len() as i64 > 10000
            || bytes + extra as i64 > 2147483648
        {
            return Err(Error::new(429, "OFFLINE_QUEUE_CAPACITY"));
        }
        for (v, reason) in pending {
            let id = v["operation_id"].as_str().unwrap();
            let state = if reason.is_some() {
                "rejected"
            } else {
                "received"
            };
            tx.execute(
                "INSERT INTO offline_operations VALUES(?,?,?,?,?,?,?,?,?,?)",
                params![
                    id,
                    v["stream_id"].as_str(),
                    envelope::sequence(&v["device_sequence"])?,
                    v["order_id"].as_str(),
                    v["owner_id"].as_str(),
                    v["kind"].as_str(),
                    v["content_sha256"].as_str(),
                    store::encoded(v),
                    crate::auth::now(),
                    v["base"]["previous_operation_id"].as_str()
                ],
            )?;
            tx.execute(
                "INSERT INTO offline_states VALUES(?,?,?,NULL)",
                params![id, state, reason],
            )?;
            tx.execute(
                "INSERT INTO offline_events(operation_id,state,at) VALUES(?,?,?)",
                params![id, state, crate::auth::now()],
            )?;
            tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
        }
    }
    for v in ops {
        super::progress::refresh(i, &tx, ctx, v)?;
    }
    super::fault(i, "intake_before_commit");
    tx.commit()?;
    super::fault(i, "intake_after_commit");
    let receipts = ops
        .iter()
        .map(|v| receipt(&c, ctx, v["operation_id"].as_str().unwrap()))
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({"protocol":FORMAT,"receipts":receipts,"offline_orders":false}))
}
