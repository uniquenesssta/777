//! Defense in depth: diagnostics are metadata, never complete business/authentication payloads.
use serde_json::Value;
fn sensitive(key: &str) -> bool {
    let k = key.to_ascii_lowercase();
    [
        "password",
        "secret",
        "ticket",
        "token",
        "authorization",
        "private_key",
        "private_key_pem",
        "body",
        "payload",
        "request",
        "response",
        "orders",
        "customer",
    ]
    .contains(&k.as_str())
        || [
            "_password",
            "_secret",
            "_token",
            "_ticket",
            "_private_key",
            "_body",
        ]
        .iter()
        .any(|suffix| k.ends_with(suffix))
}
pub(super) fn safe(value: Value) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.into_iter()
                .map(|(k, v)| {
                    let v = if sensitive(&k) {
                        Value::String("[redacted]".into())
                    } else {
                        safe(v)
                    };
                    (k, v)
                })
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.into_iter().take(64).map(safe).collect()),
        Value::String(s) if s.contains("PRIVATE KEY") || s.len() > 4096 => {
            Value::String("[omitted]".into())
        }
        v => v,
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn accidental_nested_credentials_and_business_bodies_do_not_enter_logs() {
        let v = super::safe(
            serde_json::json!({"stage":"enroll","device_id":"public-id","nested":{"authorization":"Bearer secret","device_secret":"secret","body":{"orders":[1]}}}),
        );
        let text = v.to_string();
        assert!(!text.contains("Bearer secret"));
        assert!(!text.contains("orders"));
        assert_eq!(v["device_id"], "public-id");
    }
}
