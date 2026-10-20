//! Immutable package policy, enforced before native IPC and before returning data.
//! Host authentication and its admin/sales ceiling remain authoritative.
use crate::{Action, DesktopError, Result};
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
struct Definition {
    id: String,
    required: bool,
    admin: bool,
    needs: Vec<String>,
}
pub fn validate(delivery: &str, selected: &[String]) -> Result<()> {
    let definitions: Vec<Definition> =
        serde_json::from_str(include_str!("../../permissions.json")).unwrap();
    let valid = ["manager", "sales"].contains(&delivery)
        && selected.iter().enumerate().all(|(i, id)| {
            !selected[..i].contains(id)
                && definitions
                    .iter()
                    .any(|p| &p.id == id && (!p.admin || delivery == "manager"))
        })
        && definitions.iter().all(|p| {
            (!p.required || selected.contains(&p.id))
                && (!selected.contains(&p.id) || p.needs.iter().all(|id| selected.contains(id)))
        });
    if valid {
        Ok(())
    } else {
        Err(DesktopError::new(403, "PACKAGE_PERMISSIONS_INVALID"))
    }
}
pub fn selected() -> Result<Option<Vec<String>>> {
    #[cfg(quote777_packaged)]
    {
        let metadata: Value = serde_json::from_str(include_str!(concat!(
            env!("OUT_DIR"),
            "/package-metadata.json"
        )))
        .map_err(|_| DesktopError::new(403, "PACKAGE_PERMISSIONS_INVALID"))?;
        let permissions: Vec<String> = serde_json::from_value(metadata["permissions"].clone())
            .map_err(|_| DesktopError::new(403, "PACKAGE_PERMISSIONS_INVALID"))?;
        validate(crate::startup::delivery(), &permissions)?;
        Ok(Some(permissions))
    }
    #[cfg(not(quote777_packaged))]
    {
        if crate::startup::formal() {
            let definitions: Vec<Definition> =
                serde_json::from_str(include_str!("../../permissions.json")).unwrap();
            let delivery = crate::startup::delivery();
            let permissions = definitions
                .into_iter()
                .filter(|p| delivery == "manager" || !p.admin)
                .map(|p| p.id)
                .collect::<Vec<_>>();
            validate(delivery, &permissions)?;
            return Ok(Some(permissions));
        }
        Ok(None)
    }
}
pub fn has(selected: &Option<Vec<String>>, id: &str) -> bool {
    selected.as_ref().is_none_or(|p| p.iter().any(|v| v == id))
}
pub fn require(selected: &Option<Vec<String>>, id: &str) -> Result<()> {
    if has(selected, id) {
        Ok(())
    } else {
        Err(DesktopError::new(403, "PACKAGE_PERMISSION_DENIED"))
    }
}
pub fn authorize(selected: &Option<Vec<String>>, action: &Action) -> Result<()> {
    use Action::*;
    let permission = match action {
        Bootstrap {} | Connection {} | UiDiagnostic { .. } | Recover { .. } => return Ok(()),
        Connect { .. }
        | Disconnect {}
        | ImportConnection { .. }
        | PackageTarget {}
        | VerifyPackageTarget { .. }
        | UseCurrentPackageTarget {} => {
            if crate::startup::formal() {
                return Err(DesktopError::new(403, "MANUAL_LOGIN_DISABLED"));
            }
            return Ok(());
        }
        // Provisioning is an operator action; no formal UI entry point exists.
        ImportEnrollment { .. } => return Ok(()),
        Prices {} | Calculate { .. } | Submit { .. } | LocalReceipt { .. } => "quote",
        OrderPreview { order_id, .. } | SaveOrder { order_id, .. } => {
            if order_id.is_some() {
                "edit_orders"
            } else {
                "quote"
            }
        }
        Orders { .. } | Order { .. } | OrderChanges { .. } | CustomerOrders { .. } => "orders",
        Note { .. } | SetState { .. } => "edit_orders",
        PricePreview { .. } | PublishPrices { .. } => "prices",
        Analytics { .. } => "finance",
        Settings {} | SaveSettings { .. } | BusinessDirectory {} | SaveBusinessDirectory { .. } => {
            "settings"
        }
        BackupStatus {} | Backup {} => "backup",
        CreateReport { .. } => {
            require(selected, "finance")?;
            "exports"
        }
        CreateOutput { kind, .. } => {
            if kind == "excel_admin" {
                require(selected, "finance")?;
            }
            "exports"
        }
        Outputs { .. } | RetryOutput { .. } | OpenOutputFolder { .. } => "exports",
        PickDirectory { target } => {
            if crate::startup::formal()
                && !["export_dir", "image_dir", "business_directory"].contains(&target.as_str())
            {
                return Err(DesktopError::new(403, "PACKAGE_PERMISSION_DENIED"));
            }
            if crate::startup::formal() {
                "settings"
            } else {
                return Ok(());
            }
        }
        #[cfg(all(
            debug_assertions,
            not(any(feature = "manager", feature = "sales", feature = "verification"))
        ))]
        Developer { .. } => return Ok(()),
    };
    require(selected, permission)
}
pub fn pending(selected: &Option<Vec<String>>, path: &str, body: &Value) -> Result<()> {
    let permission = match path {
        "/v1/orders" => "quote",
        "/v1/order-save" => {
            if body["order_id"].is_null() {
                "quote"
            } else {
                "edit_orders"
            }
        }
        "/v1/notes" | "/v1/state" => "edit_orders",
        "/v1/prices" => "prices",
        "/v1/outputs/report" => {
            require(selected, "finance")?;
            "exports"
        }
        "/v1/outputs" => {
            if body["kind"] == "excel_admin" {
                require(selected, "finance")?;
            }
            "exports"
        }
        p if p.starts_with("/v1/outputs/") && p.ends_with("/retry") => "exports",
        _ => return Err(DesktopError::new(403, "PACKAGE_PERMISSION_DENIED")),
    };
    require(selected, permission)
}
pub fn redact_financial(value: &mut Value) {
    match value {
        Value::Object(map) => {
            // Same public catalog projection as a sales Host response.
            if map.contains_key("pricing_mode") && map.contains_key("unit_sale") {
                map.insert("sale".into(), map["unit_sale"].clone());
                map.insert("k".into(), Value::String("1".into()));
            }
            map.remove("pricing_mode");
            if let Some(Value::Array(changes)) = map.get_mut("changes") {
                changes.retain(|row| {
                    !["成本", "利润", "K"].contains(&row["field"].as_str().unwrap_or(""))
                });
            }
            map.retain(|key, _| {
                ![
                    "cost",
                    "cost_cents",
                    "profit",
                    "profit_cents",
                    "margin",
                    "financial_display",
                    "ledger_revision",
                ]
                .contains(&key.as_str())
            });
            for v in map.values_mut() {
                redact_financial(v);
            }
        }
        Value::Array(items) => items.iter_mut().for_each(redact_financial),
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn role_dependencies_unknown_ids_and_duplicates_fail_closed() {
        for ids in [
            vec!["quote", "finance"],
            vec!["quote", "bogus"],
            vec!["quote", "quote"],
            vec!["quote", "exports"],
        ] {
            assert!(validate(
                "sales",
                &ids.into_iter().map(str::to_string).collect::<Vec<_>>()
            )
            .is_err());
        }
        assert!(validate("manager", &["quote".into(), "prices".into()]).is_err());
    }
    #[test]
    fn direct_ipc_and_old_pending_cannot_restore_removed_permissions() {
        let p = Some(vec!["quote".into()]);
        assert!(authorize(
            &p,
            &Action::Orders {
                q: "".into(),
                state: "".into(),
                offset: 0,
                view: "".into()
            }
        )
        .is_err());
        assert!(pending(&p, "/v1/order-save", &json!({"order_id":"existing"})).is_err());
        assert!(pending(&p, "/v1/outputs", &json!({"kind":"excel_admin"})).is_err());
        assert!(pending(&p, "/v1/order-save", &json!({"order_id":null})).is_ok());
    }
    #[test]
    fn historical_diff_rows_and_cost_plus_catalog_are_public_projections() {
        let mut v = json!({"items":[{"cost":"40","sale":"10","unit_sale":"60","k":"1.5","pricing_mode":"cost_plus"}],"changes":[{"field":"成本","before":"40","after":"50"},{"field":"金额","before":"60","after":"70"}]});
        redact_financial(&mut v);
        assert_eq!(
            v,
            json!({"items":[{"sale":"60","unit_sale":"60","k":"1"}],"changes":[{"field":"金额","before":"60","after":"70"}]})
        );
    }
    #[test]
    fn nested_history_and_calculations_do_not_leak_costs() {
        let mut v = json!({"income_cents":"100","history":[{"cost_cents":"20","normalized":{"cost":"0.2","sale":"1"},"financial_display":{"profit":"0.8"}}]});
        redact_financial(&mut v);
        assert_eq!(
            v,
            json!({"income_cents":"100","history":[{"normalized":{"sale":"1"}}]})
        );
    }
}
