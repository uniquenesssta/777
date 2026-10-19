//! Stable even when another workspace dependency enables serde_json/preserve_order.
use crate::{Error, Result};
use serde_json::Value;
fn ordered(v: &Value) -> Result<Value> {
    Ok(match v {
        Value::Number(_) => return Err(Error::new("OFFLINE_WIRE_NUMBER_FORBIDDEN")),
        Value::Object(m) => {
            let mut keys = m.keys().collect::<Vec<_>>();
            keys.sort_unstable();
            let mut result = serde_json::Map::new();
            for k in keys {
                if !k.is_ascii() {
                    return Err(Error::new("OFFLINE_CANONICAL_KEY_INVALID"));
                }
                result.insert(k.clone(), ordered(&m[k])?);
            }
            Value::Object(result)
        }
        Value::Array(a) => Value::Array(a.iter().map(ordered).collect::<Result<_>>()?),
        _ => v.clone(),
    })
}
pub fn encode(v: &Value) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(&ordered(v)?)?)
}
