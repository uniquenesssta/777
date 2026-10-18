use crate::{fail, service::Service, Result};
use serde::Deserialize;
use serde_json::Value;
#[derive(Deserialize)]
struct Permission {
    id: String,
    required: bool,
    admin: bool,
    needs: Vec<String>,
}
pub fn validate(delivery: &str, selected: &[String]) -> Result<()> {
    let catalog: Vec<Permission> =
        serde_json::from_str(include_str!("../../../../desktop/permissions.json"))?;
    if !["manager", "sales"].contains(&delivery) || selected.windows(2).any(|w| w[0] >= w[1]) {
        return fail(422, "PACKAGE_CAPABILITIES_INVALID");
    }
    for item in &catalog {
        if item.required && !selected.contains(&item.id) {
            return fail(422, "PACKAGE_CAPABILITIES_INVALID");
        }
    }
    for id in selected {
        let item = catalog
            .iter()
            .find(|v| v.id == *id)
            .ok_or_else(super::denied)?;
        if delivery == "sales" && item.admin || item.needs.iter().any(|v| !selected.contains(v)) {
            return fail(403, "PACKAGE_CAPABILITIES_DENIED");
        }
    }
    Ok(())
}
pub fn all() -> Vec<String> {
    let mut ids: Vec<String> = serde_json::from_str::<Vec<Permission>>(include_str!(
        "../../../../desktop/permissions.json"
    ))
    .expect("frozen capability catalog")
    .into_iter()
    .map(|p| p.id)
    .collect();
    ids.sort();
    ids
}
pub fn require(caps: &[String], id: &str) -> Result<()> {
    if caps.iter().any(|v| v == id) {
        Ok(())
    } else {
        fail(403, "PACKAGE_PERMISSION_DENIED")
    }
}
pub fn authorize(
    s: &Service,
    caps: &[String],
    method: &str,
    path: &str,
    data: &Value,
) -> Result<()> {
    let cap = match (method, path) {
        ("GET", "/v1/capabilities" | "/v1/me") => return Ok(()),
        ("GET", "/v1/prices") | ("POST", "/v1/calculate" | "/v1/orders") => "quote",
        ("POST", "/v1/order-preview" | "/v1/order-save") => {
            if data["order_id"].is_string() {
                "edit_orders"
            } else {
                "quote"
            }
        }
        ("POST", "/v1/notes" | "/v1/state") => "edit_orders",
        ("POST", "/v1/customer-orders") | ("GET", "/v1/orders") => "orders",
        ("GET", p) if p.starts_with("/v1/orders/") => "orders",
        ("GET", "/v1/analytics") => "finance",
        ("POST", "/v1/prices") => "prices",
        ("GET", "/v1/settings") => "settings",
        ("GET" | "POST", "/v1/backup") => "backup",
        ("POST", "/v1/outputs/report") => {
            require(caps, "finance")?;
            "exports"
        }
        ("GET" | "POST", "/v1/outputs") => {
            if data["kind"] == "excel_admin" {
                require(caps, "finance")?;
            }
            "exports"
        }
        ("GET" | "POST", p) if p.starts_with("/v1/outputs/") => {
            let id = p
                .trim_start_matches("/v1/outputs/")
                .split('/')
                .next()
                .unwrap_or("");
            quote_ledger::store::id(id)?;
            if let Some(o) = &s.outputs {
                let c = o.connection()?;
                let kind: String =
                    c.query_row("SELECT kind FROM jobs WHERE job_id=?", [id], |r| r.get(0))?;
                if ["excel_admin", "excel_period"].contains(&kind.as_str()) {
                    require(caps, "finance")?;
                }
            }
            "exports"
        }
        // A receipt may reveal old mutation/output details; permit only business scopes
        // and re-check any returned job after querying it in the response guard.
        ("GET", p) if p.starts_with("/v1/requests/") => "quote",
        _ => return fail(403, "PACKAGE_PERMISSION_DENIED"),
    };
    require(caps, cap)
}
pub fn redact(v: &mut Value) {
    match v {
        Value::Object(map) => {
            if map.contains_key("pricing_mode") && map.contains_key("unit_sale") {
                map.insert("sale".into(), map["unit_sale"].clone());
                map.insert("k".into(), Value::String("1".into()));
            }
            map.remove("pricing_mode");
            if let Some(Value::Array(rows)) = map.get_mut("changes") {
                rows.retain(|r| {
                    !["成本", "利润", "K"].contains(&r["field"].as_str().unwrap_or(""))
                });
            }
            map.retain(|k, _| {
                ![
                    "cost",
                    "cost_cents",
                    "profit",
                    "profit_cents",
                    "margin",
                    "financial_display",
                    "ledger_revision",
                ]
                .contains(&k.as_str())
            });
            for v in map.values_mut() {
                redact(v)
            }
        }
        Value::Array(a) => a.iter_mut().for_each(redact),
        _ => (),
    }
}
