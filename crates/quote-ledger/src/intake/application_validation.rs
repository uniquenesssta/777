//! Cross-check applied and resolved identities when opening recovery/replica data.
use super::*;
use rusqlite::OptionalExtension;
pub(super) fn verify(c: &Connection) -> Result<()> {
    let mut st=c.prepare("SELECT o.operation_id,o.order_id,o.operation_json,s.applied_request_id,r.result_json,r.actor_id,d.subject_id,d.device_id,d.package_id FROM offline_operations o JOIN offline_states s USING(operation_id) JOIN offline_streams d USING(stream_id) LEFT JOIN requests r ON r.request_id=s.applied_request_id WHERE s.state='applied'")?;
    let mut rows = st.query([])?;
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let oid: String = row.get(1)?;
        let raw: String = row.get(2)?;
        let operation: Value = serde_json::from_str(&raw)?;
        let request: Option<String> = row.get(3)?;
        let result: Option<String> = row.get(4)?;
        let result: Value =
            serde_json::from_str(&result.ok_or_else(|| Error::new("INVALID_DATABASE"))?)?;
        if request.as_deref() != Some(&id)
            || result["request_id"] != id
            || result["order_id"] != oid
            || row.get::<_, String>(5)? != row.get::<_, String>(6)?
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
        if operation["origin"] == "server_resolution" {
            if operation["protocol"] != "777-offline-resolution-v1"
                || row.get::<_, String>(7)? != "server-resolution"
                || row.get::<_, String>(8)? != "server-resolution"
            {
                return Err(Error::new("INVALID_DATABASE"));
            }
            let decision: Option<String> = c
                .query_row(
                    "SELECT decision_json FROM offline_resolutions WHERE resolution_operation_id=?",
                    [&id],
                    |r| r.get(0),
                )
                .optional()?;
            let decision: Value =
                serde_json::from_str(&decision.ok_or_else(|| Error::new("INVALID_DATABASE"))?)?;
            let (fingerprint,): (String,) = c.query_row(
                "SELECT fingerprint FROM requests WHERE request_id=?",
                [&id],
                |r| Ok((r.get(0)?,)),
            )?;
            let reviewer: String = row.get(5)?;
            let canonical = super::canonical::encode(&operation["payload"])?;
            let expected = store::hash(
                [
                    reviewer.as_bytes(),
                    b"\n777-offline-resolution-v1\n",
                    &canonical,
                ]
                .concat(),
            );
            let disposition = match operation["payload"]["decision"].as_str() {
                Some("keep_current") => "kept",
                Some("merge_into") => "merged",
                Some("apply_candidate") => "applied",
                _ => return Err(Error::new("INVALID_DATABASE")),
            };
            if decision["request_id"] != id
                || decision["source_operation_id"] != operation["source_operation_id"]
                || decision["reviewer_subject"] != reviewer
                || operation["reviewer_subject"] != reviewer
                || decision["fingerprint"] != fingerprint
                || fingerprint != expected
                || decision["decision"] != operation["payload"]
                || decision["disposition"] != disposition
            {
                return Err(Error::new("INVALID_DATABASE"));
            }
        } else if operation.get("origin").is_some()
            || operation["protocol"] != "777-offline-order-v1"
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
    }
    let mut st=c.prepare("SELECT o.operation_id,o.content_sha256,f.candidate_json FROM offline_conflicts f JOIN offline_operations o USING(operation_id)")?;
    let mut rows = st.query([])?;
    while let Some(row) = rows.next()? {
        let candidate: Value = serde_json::from_str(&row.get::<_, String>(2)?)?;
        if candidate["operation_id"] != row.get::<_, String>(0)?
            || candidate["content_sha256"] != row.get::<_, String>(1)?
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
    }
    let invalid:i64=c.query_row("SELECT count(*) FROM offline_resolutions d JOIN offline_states s ON s.operation_id=d.operation_id JOIN offline_states r ON r.operation_id=d.resolution_operation_id WHERE s.state NOT IN ('conflict','rejected') OR r.state!='applied'",[],|r|r.get(0))?;
    if invalid != 0 {
        return Err(Error::new("INVALID_DATABASE"));
    }
    let invalid:i64=c.query_row("SELECT count(*) FROM order_changes_feed f JOIN orders o USING(order_id) WHERE f.owner_id!=o.owner_id OR f.order_revision<1 OR f.order_revision>o.revision",[],|r|r.get(0))?;
    if invalid != 0 {
        return Err(Error::new("INVALID_DATABASE"));
    }
    Ok(())
}
