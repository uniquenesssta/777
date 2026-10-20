use super::*;
use quote_core::models::{PriceItem, Prices};
fn price(v: &Value) -> Result<PriceItem> {
    let mut p = serde_json::Map::new();
    for k in [
        "product_id",
        "sale",
        "cost",
        "k",
        "single",
        "pricing_mode",
        "discount_eligible",
    ] {
        if let Some(v) = v.get(k) {
            p.insert(k.into(), v.clone());
        }
    }
    // Public calculation has no cost input. This internal zero is discarded from
    // its result; it is never a financial fact or an upload-derived amount.
    p.entry("cost").or_insert(json!("0"));
    serde_json::from_value(Value::Object(p)).map_err(json_error)
}
impl Local {
    pub(crate) fn calculate(&self, body: &Value) -> Result<Value> {
        let ctx = self.context()?;
        permit(&ctx, "quote")?;
        let snapshot = &body["snapshot"];
        let q = quote_ledger::store::decode_quote(snapshot.clone())
            .map_err(|_| fault("INVALID_QUOTE"))?;
        let catalog = self
            .meta(&format!(
                "price:{}",
                snapshot["price_version_id"].as_str().unwrap_or("")
            ))?
            .ok_or_else(|| fault("PRICE_VERSION_UNAVAILABLE"))?;
        let prices = Prices {
            price_version_id: catalog["price_version_id"].clone(),
            items: catalog["items"]
                .as_array()
                .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
                .iter()
                .map(price)
                .collect::<Result<_>>()?,
        };
        let old = body["order_id"]
            .as_str()
            .map(|id| self.order(id))
            .transpose()?;
        if let Some(old) = &old {
            if old["revision"] != body["expected_revision"] || old["state"] != "active" {
                return Err(fault("REVISION_OR_PRICE_CONFLICT"));
            }
        }
        let sources = body["sources"].as_array();
        if sources.is_some_and(|v| v.len() != q.lines.len()) {
            return Err(fault("SOURCE_LINE_INVALID"));
        }
        let mut frozen = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for (n, raw) in q.lines.iter().enumerate() {
            let source = sources.and_then(|a| a[n].as_str());
            let saved = if let Some(id) = source {
                if !seen.insert(id) {
                    return Err(fault("SOURCE_LINE_INVALID"));
                }
                Some(
                    old.as_ref()
                        .and_then(|o| o["lines"].as_array())
                        .and_then(|ls| ls.iter().find(|l| l["line_id"] == id))
                        .ok_or_else(|| fault("SOURCE_LINE_INVALID"))?,
                )
            } else {
                None
            };
            frozen.push(match (raw,saved){
                (quote_core::models::Line::Normal{product_id,..},Some(l)) if l["raw"]["product_id"]==*product_id=>Some(price(&json!({"product_id":product_id,"sale":l["normalized"]["sale"],"cost":l["normalized"].get("cost").cloned().unwrap_or(json!("0")),"k":l["normalized"].get("k").cloned().unwrap_or(json!("1")),"single":l["normalized"].get("h").is_none(),"discount_eligible":l["normalized"]["discount_eligible"].as_str().map(|v|v=="true")}))?),
                _=>None
            });
        }
        let result = quote_core::calculation::calculate_with_prices(&q, &prices, Some(&frozen));
        let lines = result
            .lines
            .as_deref()
            .unwrap_or(&[])
            .iter()
            .map(|line| {
                let normalized = line
                    .normalized
                    .iter()
                    .cloned()
                    .collect::<std::collections::BTreeMap<_, _>>();
                let mut out = line.amounts.cents();
                out["raw"] = quote_ledger::store::legacy_line(&line.raw);
                out["sequence"] = json!(line.sequence);
                out["normalized"] = json!(normalized);
                out["subtotal_before_cents"] = json!(line.subtotal_before.to_string());
                out
            })
            .collect::<Vec<_>>();
        let mut value = json!({"status":result.status,"price_version_id":result.price_version_id,"lines":lines,"totals":result.totals.map(|a|a.cents()),"issues":result.issues,"warnings":result.warnings});
        public(&mut value, &ctx);
        Ok(value)
    }
}
