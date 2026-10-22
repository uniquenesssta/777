use super::*;
use rusqlite::{params, OptionalExtension};
impl Local {
    pub(crate) fn order(&self, id: &str) -> Result<Value> {
        let ctx = self.context()?;
        permit(&ctx, "orders")?;
        let alias = self.meta(&format!("alias:{id}"))?;
        let id = alias
            .as_ref()
            .and_then(Value::as_str)
            .filter(|target| {
                self.c
                    .query_row(
                        "SELECT EXISTS(SELECT 1 FROM local_orders WHERE id=?)",
                        [target],
                        |r| r.get::<_, bool>(0),
                    )
                    .unwrap_or(false)
            })
            .unwrap_or(id);
        let raw: Option<Vec<u8>> = self
            .c
            .query_row("SELECT working FROM local_orders WHERE id=?", [id], |r| {
                r.get(0)
            })
            .optional()
            .map_err(sql)?;
        let mut v = self.decode(&raw.ok_or_else(|| DesktopError::new(404, "NOT_FOUND"))?)?;
        if ctx["binding"]["role"] != "admin" && v["owner_id"] != ctx["binding"]["subject"] {
            return Err(DesktopError::new(404, "NOT_FOUND"));
        }
        if v["deleted"] == true {
            return Err(DesktopError::new(404, "NOT_FOUND"));
        }
        public(&mut v, &ctx);
        Ok(v)
    }
    pub(crate) fn save(&self, kind: &str, body: &Value) -> Result<Value> {
        self.transaction(|| {
            if let Some(v) = self.replay(kind, body)? {
                return Ok(v);
            }
            let result = self.save_on(kind, body)?;
            self.remember_command(kind, body, &result)?;
            Ok(result)
        })
    }
    fn save_on(&self, kind: &str, body: &Value) -> Result<Value> {
        let ctx = self.writable()?;
        let b = &ctx["lease"]["body"];
        let editing = body["order_id"].as_str();
        permit(
            &ctx,
            if editing.is_some() {
                "edit_orders"
            } else {
                "quote"
            },
        )?;
        let id = editing
            .map(str::to_owned)
            .unwrap_or(crate::types::new_id()?);
        let old = editing.map(|id| self.order(id)).transpose()?;
        if old
            .as_ref()
            .is_some_and(|v| v["revision"] != body["expected_revision"])
        {
            return Err(fault("REVISION_OR_PRICE_CONFLICT"));
        }
        let previous: Option<String> = self
            .c
            .query_row(
                "SELECT last_operation FROM local_orders WHERE id=?",
                [&id],
                |r| r.get(0),
            )
            .optional()
            .map_err(sql)?
            .flatten();
        let confirmed: Option<Vec<u8>> = self
            .c
            .query_row(
                "SELECT confirmed FROM local_orders WHERE id=?",
                [&id],
                |r| r.get(0),
            )
            .optional()
            .map_err(sql)?
            .flatten();
        let confirmed = confirmed.map(|v| self.decode(&v)).transpose()?;
        if let Some(previous) = &previous {
            let raw: Vec<u8> = self
                .c
                .query_row(
                    "SELECT raw FROM local_operations WHERE id=?",
                    [previous],
                    |r| r.get(0),
                )
                .map_err(sql)?;
            if self.decode(&raw)?["stream_id"] != b["stream_id"] {
                return Err(fault("LOCAL_ORDER_REQUIRES_RECONCILIATION"));
            }
        }
        let base = if editing.is_none() {
            json!({"order_revision":null,"previous_operation_id":null})
        } else if let Some(p) = previous {
            json!({"order_revision":null,"previous_operation_id":p})
        } else {
            json!({"order_revision":confirmed.as_ref().map(|v|v["revision"].clone()).unwrap_or(Value::Null),"previous_operation_id":null})
        };
        let revision = old
            .as_ref()
            .map(|v| number(&v["revision"]))
            .transpose()?
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| fault("LOCAL_VERSION_INVALID"))?;
        let mut next=old.clone().unwrap_or_else(||json!({"order_id":id,"owner_id":b["subject"],"revision":"0","state":"active","created_at":stamp(),"notes":[],"history":[]}));
        let (wire_kind, mut payload) = if kind == "save" {
            for k in ["customer", "order_ref", "wechat"] {
                let s = body["details"][k]
                    .as_str()
                    .ok_or_else(|| fault("INVALID_DETAILS"))?;
                if s.chars().count() > 256 || s.contains('\0') {
                    return Err(fault("INVALID_DETAILS"));
                }
            }
            let calc = self.calculate(body)?;
            if calc["status"] != "ok" {
                return Err(fault("CALCULATION_REQUIRED"));
            }
            let sources = body["sources"].as_array();
            let mut lines = calc["lines"]
                .as_array()
                .ok_or_else(|| fault("INVALID_QUOTE"))?
                .clone();
            for (n, line) in lines.iter_mut().enumerate() {
                line["line_id"] = sources
                    .and_then(|v| v.get(n))
                    .filter(|v| v.is_string())
                    .cloned()
                    .unwrap_or(json!(crate::types::new_id()?));
                line["price_version_id"] = old
                    .as_ref()
                    .and_then(|o| o["lines"].as_array())
                    .and_then(|ls| {
                        ls.iter().find(|l| {
                            l["line_id"] == line["line_id"]
                                && l["raw"]["product_id"] == line["raw"]["product_id"]
                        })
                    })
                    .and_then(|l| l.get("price_version_id"))
                    .cloned()
                    .unwrap_or_else(|| body["snapshot"]["price_version_id"].clone());
            }
            let mut customer = body["customer"].clone();
            if customer.is_null() {
                customer = json!({})
            }
            if let Some(cid) = customer["customer_id"].as_str() {
                let existing = self.all()?.into_iter().find(|v| v["customer_id"] == cid);
                if let Some(anchor) = existing {
                    customer = json!({"anchor_order_id":anchor["order_id"]});
                }
            }
            let anchor = customer["anchor_order_id"]
                .as_str()
                .map(|id| self.order(id))
                .transpose()?;
            next["customer_id"] = anchor
                .as_ref()
                .map(|v| v["customer_id"].clone())
                .or_else(|| old.as_ref().map(|v| v["customer_id"].clone()))
                .unwrap_or(Value::Null);
            if next["customer_id"].is_null() && customer.as_object().is_some_and(|v| v.is_empty()) {
                let name = body["details"]["customer"].as_str().unwrap().trim();
                let wechat = body["details"]["wechat"].as_str().unwrap().trim();
                let candidates = self
                    .all()?
                    .into_iter()
                    .filter(|v| {
                        (!name.is_empty() && v["details"]["customer"] == name)
                            || (!wechat.is_empty() && v["details"]["wechat"] == wechat)
                    })
                    .collect::<Vec<_>>();
                let ids = candidates
                    .iter()
                    .filter_map(|v| v["customer_id"].as_str())
                    .collect::<std::collections::HashSet<_>>();
                if ids.len() == 1
                    && candidates.iter().all(|v| {
                        (name.is_empty() || v["details"]["customer"] == name)
                            && (wechat.is_empty() || v["details"]["wechat"] == wechat)
                    })
                {
                    next["customer_id"] = json!(ids.into_iter().next().unwrap());
                }
            }
            if next["customer_id"].is_null() {
                next["customer_id"] = customer
                    .get("customer_id")
                    .cloned()
                    .unwrap_or(json!(crate::types::new_id()?));
            }
            if customer["new_customer"] == true {
                next["customer_id"] = json!(crate::types::new_id()?);
            }
            next["final_price"] = body["snapshot"]["final_price"].clone();
            next["details"] = body["details"].clone();
            next["lines"] = json!(lines);
            next["price_version_id"] = body["snapshot"]["price_version_id"].clone();
            for k in [
                "income_cents",
                "cost_cents",
                "profit_cents",
                "financial_display",
            ] {
                if let Some(v) = calc["totals"].get(k) {
                    next[k] = v.clone();
                }
            }
            if let Some(old) = &old {
                let mut changes = Vec::new();
                for line in next["lines"].as_array().unwrap() {
                    let existing = old["lines"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .find(|l| l["line_id"] == line["line_id"]);
                    match existing {
                        None => changes
                            .push(json!({"op":"add","line_id":line["line_id"],"raw":line["raw"]})),
                        Some(existing) if existing["raw"] != line["raw"] => changes.push(
                            json!({"op":"replace","line_id":line["line_id"],"raw":line["raw"]}),
                        ),
                        _ => (),
                    }
                }
                for line in old["lines"].as_array().unwrap() {
                    if !next["lines"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|l| l["line_id"] == line["line_id"])
                    {
                        changes.push(json!({"op":"remove","line_id":line["line_id"]}));
                    }
                }
                let mut details = json!({});
                for k in ["customer", "order_ref", "wechat"] {
                    if old["details"][k] != next["details"][k] {
                        details[k] = next["details"][k].clone();
                    }
                }
                (
                    "edit",
                    json!({"detail_changes":details,"line_changes":changes,"customer":customer}),
                )
            } else {
                (
                    "create",
                    json!({"snapshot":{"price_version_id":next["price_version_id"],"lines":next["lines"].as_array().unwrap().iter().map(|l|json!({"line_id":l["line_id"],"raw":l["raw"]})).collect::<Vec<_>>()},"details":next["details"],"customer":customer}),
                )
            }
        } else if kind == "note" {
            let text = body["body"]
                .as_str()
                .filter(|s| !s.trim().is_empty() && s.chars().count() <= 4096 && !s.contains('\0'))
                .ok_or_else(|| fault("INVALID_NOTE"))?;
            let nid = crate::types::new_id()?;
            next["notes"]
                .as_array_mut()
                .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
                .push(
                    json!({"note_id":nid,"body":text,"author":b["subject"],"created_at":stamp()}),
                );
            ("append_note", json!({"note_id":nid,"body":text}))
        } else {
            if ctx["binding"]["role"] != "admin" {
                return Err(DesktopError::new(403, "ADMIN_REQUIRED"));
            }
            let state = body["state"]
                .as_str()
                .filter(|s| ["active", "void"].contains(s))
                .ok_or_else(|| fault("INVALID_STATE"))?;
            let reason = body["reason"]
                .as_str()
                .filter(|s| !s.trim().is_empty() && s.chars().count() <= 4096)
                .ok_or_else(|| fault("INVALID_STATE"))?;
            next["state"] = json!(state);
            ("set_state", json!({"state":state,"reason":reason}))
        };
        if kind == "save" {
            if wire_kind == "create" {
                if !next["final_price"].is_null() {
                    payload["snapshot"]["final_price"] = next["final_price"].clone();
                }
            } else if old
                .as_ref()
                .is_some_and(|v| v["final_price"] != next["final_price"])
            {
                payload["final_price"] = next["final_price"].clone();
            }
        }
        next["revision"] = json!(revision.to_string());
        let op = if body["operation_id"].is_null() {
            crate::types::new_id()?
        } else {
            identifier(&body["operation_id"])?.to_owned()
        };
        let stream = b["stream_id"].as_str().unwrap();
        let seq: i64 = self
            .c
            .query_row(
                "SELECT coalesce(max(sequence),0)+1 FROM local_operations WHERE stream=?",
                [stream],
                |r| r.get(0),
            )
            .map_err(sql)?;
        let seq = self.checkpoint(Some((stream, seq)), now())?;
        let mut raw = json!({"protocol":"777-offline-order-v1","site_id":b["site_id"],"ledger_id":b["ledger_id"],"device_id":b["device_id"],"stream_id":stream,"owner_id":next["owner_id"],"lease_id":b["lease_id"],"rule_version":b["rule_version"],"numeric_profile":b["numeric_profile"],"operation_id":op,"device_sequence":seq.to_string(),"order_id":id,"kind":wire_kind,"base":base,"created_at":stamp(),"payload":payload});
        raw["content_sha256"] = json!(digest("777-offline-order-v1", &raw)?);
        self.insert_operation(&raw)?;
        if let Some(old) = &old {
            if kind == "save" {
                self.history(old, &next)?;
            }
        }
        public(&mut next, &ctx);
        next["history"] = json!(self.history_summary(&id)?);
        self.c.execute("INSERT INTO local_orders(id,confirmed,working,revision,last_operation) VALUES(?,NULL,?,?,?) ON CONFLICT(id) DO UPDATE SET working=excluded.working,revision=excluded.revision,last_operation=excluded.last_operation",params![id,self.encode(&next)?,revision,op]).map_err(sql)?;
        Ok(
            json!({"order_id":id,"revision":revision.to_string(),"request_id":op,"income_cents":next["income_cents"]}),
        )
    }
}
