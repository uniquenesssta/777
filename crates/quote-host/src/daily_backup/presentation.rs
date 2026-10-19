//! Aggregate delivery truth without publishing hidden destinations or failure details.
use serde_json::{json, Value};
pub(super) fn complete(entry: &Value) -> bool {
    entry["normal"]["ok"] == true && entry["hidden"]["ok"] == true
}
pub fn public_status(state: &Value) -> Value {
    let latest = state["entries"]
        .as_object()
        .and_then(|rows| rows.iter().max_by_key(|(date, _)| *date));
    match latest {
        Some((_, entry)) => {
            json!({"delivery_complete":complete(entry),"delivery_state":if complete(entry){"complete"}else if entry["normal"]["ok"]==true||entry["hidden"]["ok"]==true{"partial"}else{"failed"}})
        }
        None => json!({}),
    }
}
