//! Preserve manual settlement on submission; identify incompatible remote hosts.
use super::*;
impl Desktop {
    pub(super) async fn preview_order(&mut self, context: &Value) -> Result<Value> {
        let result = self
            .request("POST", "/v1/order-preview", Some(context))
            .await;
        if result.as_ref().is_err_and(|e| e.code == "INVALID_FIELDS")
            && context["snapshot"]["final_price"]
                .as_str()
                .is_some_and(|v| !v.trim().is_empty())
        {
            // Probe only after a field rejection. Never retry without the agreed price.
            if let Ok(capabilities) = self.request("GET", "/v1/capabilities", None).await {
                if needs_update(&capabilities) {
                    quote_diagnostics::event(
                        "desktop.quote.host_update_required",
                        json!({
                            "target": self.session()?.connection.url,
                            "feature":"final_order_price",
                        }),
                    );
                    return Err(DesktopError::new(409, "FINAL_PRICE_HOST_UPDATE_REQUIRED"));
                }
            }
        }
        result
    }
}
fn needs_update(capabilities: &Value) -> bool {
    capabilities["protocol"] == "777-service-v1" && capabilities["final_order_price"] != true
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_known_older_hosts_are_reported_as_missing_settlement_support() {
        assert!(needs_update(&json!({"protocol":"777-service-v1"})));
        assert!(!needs_update(
            &json!({"protocol":"777-service-v1","final_order_price":true})
        ));
        assert!(!needs_update(&json!({"error":"UNAUTHORIZED"})));
    }
}
