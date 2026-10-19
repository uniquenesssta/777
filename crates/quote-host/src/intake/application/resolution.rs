//! Decisions have their own identity and trusted server origin; originals stay unchanged.
use super::super::{envelope, payload, storage, Intake};
use super::{engine, merge, plan};
use crate::{
    protocol::{fields, text},
    Error, Result,
};
use quote_ledger::{
    journal,
    store::{self, Actor},
};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
pub(super) fn resolve(i: &Intake, actor: &Actor, data: &Value) -> Result<Value> {
    if !super::enabled(i) {
        return Err(Error::new(426, "OFFLINE_APPLICATION_NOT_ENABLED"));
    }
    fields(
        data,
        &[
            "protocol",
            "request_id",
            "operation_id",
            "expected_revision",
            "decision",
            "reason",
        ],
        &["payload", "target_order_id", "allow_duplicate"],
    )?;
    let rid = envelope::uuid(&data["request_id"])?;
    let id = envelope::uuid(&data["operation_id"])?;
    text(&data["reason"], 4096, true)?;
    let expected = if data["expected_revision"] == "0" {
        0
    } else {
        envelope::sequence(&data["expected_revision"])?
    };
    let decision = text(&data["decision"], 32, true)?;
    if !["keep_current", "apply_candidate", "merge_into"].contains(&decision)
        || data.get("allow_duplicate").is_some_and(|v| !v.is_boolean())
    {
        return Err(Error::new(422, "INVALID_FIELDS"));
    }
    if decision != "merge_into" && data.get("target_order_id").is_some() {
        return Err(Error::new(422, "INVALID_FIELDS"));
    }
    let fingerprint = store::hash(
        [
            actor.subject.as_bytes(),
            b"\n777-offline-resolution-v1\n",
            &envelope::canonical(data)?,
        ]
        .concat(),
    );
    let mut c = store::open(&i.ledger, true)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let old: Option<(String, String)> = tx
        .query_row(
            "SELECT fingerprint,result_json FROM requests WHERE request_id=?",
            [rid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((hash, raw)) = old {
        if hash != fingerprint {
            return Err(Error::new(409, "RESOLUTION_ID_CONFLICT"));
        }
        return Ok(serde_json::from_str(&raw)?);
    }
    if i.outputs
        .as_ref()
        .map(|o| o.has_request(rid))
        .transpose()?
        .unwrap_or(false)
        || tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM offline_operations WHERE operation_id=?)",
            [rid],
            |r| r.get::<_, bool>(0),
        )?
    {
        return Err(Error::new(409, "RESOLUTION_ID_CONFLICT"));
    }
    let row:Option<(String,String)>=tx.query_row("SELECT o.operation_json,s.state FROM offline_operations o JOIN offline_states s USING(operation_id) LEFT JOIN offline_resolutions r USING(operation_id) WHERE o.operation_id=? AND r.operation_id IS NULL",[id],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
    let (raw, state) =
        row.ok_or_else(|| Error::new(409, "CONFLICT_ALREADY_RESOLVED_OR_MISSING"))?;
    if !["conflict", "rejected"].contains(&state.as_str()) {
        return Err(Error::new(409, "OPERATION_NOT_REVIEWABLE"));
    }
    let original: Value = serde_json::from_str(&raw)?;
    let mut v = original.clone();
    if let Some(p) = data.get("payload") {
        v["payload"] = p.clone();
        payload::validate(&v)?;
    }
    if v["rule_version"] != quote_core::models::RULE_VERSION
        || v["numeric_profile"] != quote_core::models::NUMERIC_PROFILE
    {
        return Err(merge::conflict("BUSINESS_RULE_REQUIRES_CONVERSION"));
    }
    let target = if decision == "merge_into" {
        envelope::uuid(&data["target_order_id"])?
    } else {
        v["order_id"].as_str().unwrap()
    };
    let current = plan::current(&tx, target)?;
    if current.as_ref().map_or(0, |o| o.revision) != expected {
        return Err(merge::conflict("RESOLUTION_VERSION_CONFLICT"));
    }
    if current
        .as_ref()
        .is_some_and(|o| o.owner_id != v["owner_id"])
    {
        return Err(Error::new(403, "FORBIDDEN"));
    }
    let original_current = plan::current(&tx, v["order_id"].as_str().unwrap())?;
    let original_base = original_current
        .as_ref()
        .and_then(|cur| plan::basis(&tx, &v, cur).ok());
    engine::preserve(
        &tx,
        &original,
        original_base.as_ref(),
        original_current.as_ref(),
        "DEVELOPER_REVIEW",
    )?;
    let server = json!({"protocol":"777-offline-resolution-v1","origin":"server_resolution","operation_id":rid,"source_operation_id":id,"reviewer_subject":actor.subject,"stream_id":rid,"device_id":"server-resolution","device_sequence":"1","order_id":target,"owner_id":v["owner_id"],"kind":v["kind"],"base":{"order_revision":expected.to_string(),"previous_operation_id":null},"created_at":store::now().replace("+00:00","Z"),"payload":data});
    let mut server = server;
    server["content_sha256"] = json!(envelope::digest(&server)?);
    let server_raw = store::encoded(&server);
    if server_raw.len() > 262144 || storage::retained(&tx)? + server_raw.len() as i64 > 2147483648 {
        return Err(Error::new(429, "OFFLINE_QUEUE_CAPACITY"));
    }
    tx.execute(
        "INSERT INTO offline_streams VALUES(?,?,?,'server-resolution',0,0,?)",
        params![rid, "server-resolution", actor.subject, crate::auth::now()],
    )?;
    tx.execute(
        "INSERT INTO offline_operations VALUES(?,?,1,?,?,?,?,?,?,NULL)",
        params![
            rid,
            rid,
            target,
            v["owner_id"].as_str(),
            v["kind"].as_str(),
            server["content_sha256"].as_str(),
            server_raw,
            crate::auth::now()
        ],
    )?;
    let result = if decision == "keep_current" {
        journal::record(
            &tx,
            journal::Change {
                request_id: rid,
                actor,
                operation: "offline_keep",
                fingerprint: &fingerprint,
                result: json!({"order_id":target,"revision":expected,"decision":decision,"source_operation_id":id}),
                order_id: current.as_ref().map(|o| o.order_id.as_str()),
                before: &Value::Null,
            },
        )?
    } else {
        let lease_raw: String = tx.query_row(
            "SELECT lease_json FROM offline_leases WHERE lease_id=?",
            [v["lease_id"].as_str()],
            |r| r.get(0),
        )?;
        let lease: Value = serde_json::from_str(&lease_raw)?;
        let kind = v["kind"].as_str().unwrap();
        if kind == "create" && decision != "merge_into" && current.is_some() {
            return Err(merge::conflict("ORDER_ID_COLLISION"));
        }
        let mut next = plan::propose(
            &v,
            if kind == "create" {
                None
            } else {
                current.as_ref()
            },
            lease["body"]["price_version_id"].as_str().unwrap(),
        )?;
        let kind = if decision == "merge_into" {
            if kind != "create" || next.lines.iter().any(|l| l.raw["line_kind"] == "discount") {
                return Err(merge::conflict("MERGE_REQUIRES_EXPLICIT_LINE_EDIT"));
            }
            let mut target = current
                .clone()
                .filter(|o| o.state == "active")
                .ok_or_else(|| merge::conflict("ORDER_STATE_CONFLICT"))?;
            target.lines.extend(next.lines);
            next = target;
            "edit"
        } else {
            kind
        };
        next.revision = expected;
        if data["allow_duplicate"] != true && plan::duplicate(&tx, &next)?.is_some() {
            return Err(merge::conflict("POSSIBLE_DUPLICATE_ORDER"));
        }
        let choice = if decision == "merge_into" {
            json!({})
        } else {
            plan::customer(&tx, actor, &next, &v["payload"]["customer"])?
        };
        quote_ledger::application::apply(
            &tx,
            quote_ledger::application::Change {
                actor,
                request: rid,
                fingerprint: &fingerprint,
                kind,
                order: &next,
                payload: &v["payload"],
                customer: &choice,
            },
        )?
    };
    tx.execute(
        "INSERT INTO offline_states VALUES(?,'applied',NULL,?)",
        params![rid, rid],
    )?;
    tx.execute(
        "INSERT INTO offline_events(operation_id,state,at) VALUES(?,'applied',?)",
        params![rid, crate::auth::now()],
    )?;
    let disposition = if decision == "keep_current" {
        "kept"
    } else if decision == "merge_into" {
        "merged"
    } else {
        "applied"
    };
    let record = json!({"format":"777-offline-resolution-v1","request_id":rid,"source_operation_id":id,"reviewer_subject":actor.subject,"fingerprint":fingerprint,"disposition":disposition,"decision":data});
    tx.execute(
        "INSERT INTO offline_resolutions VALUES(?,?,?)",
        params![id, rid, store::encoded(&record)],
    )?;
    tx.execute("UPDATE offline_meta SET revision=revision+1 WHERE id=1", [])?;
    super::super::fault(i, "application_before_commit");
    tx.commit()?;
    super::super::fault(i, "application_after_commit");
    Ok(result)
}
