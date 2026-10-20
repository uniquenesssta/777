//! Keep IPC validation failures inside the structured, bounded diagnostic path.
use crate::{Action, DesktopError, Result};
use serde_json::Value;

impl Action {
    pub fn from_request(value: Value) -> Result<Self> {
        // Do not log the serde error: unknown field names and values may contain
        // credentials or business data. Formal builds leave diagnostics disabled.
        serde_json::from_value(value).map_err(|_| DesktopError::new(400, "DESKTOP_REQUEST_INVALID"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn malformed_requests_return_a_safe_structured_error_without_relaxing_validation() {
        for value in [
            json!({"action":"connection","secret-payload":"private"}),
            json!({"action":"private-unknown-action"}),
            json!({"action":"connect","connection":false}),
            Value::Null,
        ] {
            let Err(error) = Action::from_request(value) else {
                panic!("invalid request accepted");
            };
            assert_eq!(
                serde_json::to_value(error).unwrap(),
                json!({"status":400,"code":"DESKTOP_REQUEST_INVALID"})
            );
        }
        assert!(matches!(
            Action::from_request(json!({"action":"connection"})),
            Ok(Action::Connection {})
        ));
    }

    #[cfg(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    ))]
    #[test]
    fn saved_business_preferences_are_rejected_but_package_options_are_accepted() {
        let options = json!({"op":"save_package","output":"D:\\Packages","version":"0.1.0","runtime":"downloadBootstrapper"});
        let mut saved = options.clone();
        saved["schema"] = json!("777-developer-v1");
        saved["root"] = json!("D:\\Dev");
        assert!(Action::from_request(json!({"action":"developer","request":saved})).is_err());
        let action =
            Action::from_request(json!({"action":"developer","request":options.clone()})).unwrap();
        let Action::Developer { request } = action else {
            panic!("wrong action")
        };
        assert_eq!(serde_json::to_value(request).unwrap(), options);
        for delivery in ["manager", "sales"] {
            assert!(Action::from_request(json!({"action":"developer","request":{"op":"package","delivery":delivery,"permissions":["quote"]}})).is_ok());
        }
    }
}
