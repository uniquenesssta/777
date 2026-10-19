use super::*;
use crate::protocol::fields;
use serde_json::json;
pub(super) fn handle(
    i: &Intake,
    method: &str,
    path: &str,
    token: &str,
    data: &Value,
) -> Result<Value> {
    let ctx = context::load(i, token)?;
    let _guard = capacity::begin(&i.capacity, &ctx.device)?;
    if method != "POST" {
        return Err(Error::new(405, "METHOD_NOT_ALLOWED"));
    }
    match path {
        "/v1/offline/lease" => leases::issue(i, &ctx, data),
        "/v1/offline/operations" => {
            fields(data, &["protocol", "batch_id", "operations"], &[])?;
            if data["protocol"] != FORMAT {
                return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
            }
            envelope::uuid(&data["batch_id"])?;
            let ops = data["operations"]
                .as_array()
                .filter(|v| !v.is_empty() && v.len() <= 32)
                .ok_or_else(|| Error::new(413, "OFFLINE_BATCH_LIMIT"))?;
            if serde_json::to_vec(data)?.len() > 1048576 {
                return Err(Error::new(413, "BODY_TOO_LARGE"));
            }
            storage::receive(i, &ctx, ops)
        }
        "/v1/offline/receipts" => {
            fields(data, &["protocol", "operation_ids"], &[])?;
            if data["protocol"] != FORMAT {
                return Err(Error::new(426, "OFFLINE_PROTOCOL_UNSUPPORTED"));
            }
            let ids = data["operation_ids"]
                .as_array()
                .filter(|v| !v.is_empty() && v.len() <= 32)
                .ok_or_else(|| Error::new(413, "OFFLINE_BATCH_LIMIT"))?;
            let c = store::open(&i.ledger, false)?;
            let receipts = ids
                .iter()
                .map(|v| storage::receipt(&c, &ctx, envelope::uuid(v)?))
                .collect::<Result<Vec<_>>>()?;
            Ok(json!({"protocol":FORMAT,"receipts":receipts}))
        }
        _ => Err(Error::new(404, "NOT_FOUND")),
    }
}
