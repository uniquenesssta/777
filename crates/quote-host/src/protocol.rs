use crate::{fail, Error, Result};
use quote_core::models::{Prices, Quote, NUMERIC_PROFILE, RULE_VERSION};
use quote_ledger::store::{self, Actor};
use serde::{
    de::{self, MapAccess, SeqAccess, Visitor},
    Deserialize, Deserializer,
};
use serde_json::{json, Map, Value};
use std::fmt;
pub const BODY_LIMIT: usize = 1024 * 1024;
// Deserialize Value with duplicate detection at every object level. Financial
// numbers are strings; unknown/huge numbers are never converted to floats.
struct Unique(Value);
impl<'de> Deserialize<'de> for Unique {
    fn deserialize<D: Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Unique;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("unique-key JSON")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> std::result::Result<Unique, E> {
                Ok(Unique(json!(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> std::result::Result<Unique, E> {
                Ok(Unique(json!(v)))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> std::result::Result<Unique, E> {
                Ok(Unique(json!(v)))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> std::result::Result<Unique, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| Unique(Value::Number(n)))
                    .ok_or_else(|| E::custom("nonfinite"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> std::result::Result<Unique, E> {
                Ok(Unique(json!(v)))
            }
            fn visit_string<E: de::Error>(self, v: String) -> std::result::Result<Unique, E> {
                Ok(Unique(json!(v)))
            }
            fn visit_none<E: de::Error>(self) -> std::result::Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut a: A,
            ) -> std::result::Result<Unique, A::Error> {
                let mut v = vec![];
                while let Some(x) = a.next_element::<Unique>()? {
                    v.push(x.0)
                }
                Ok(Unique(Value::Array(v)))
            }
            fn visit_map<A: MapAccess<'de>>(
                self,
                mut a: A,
            ) -> std::result::Result<Unique, A::Error> {
                let mut v = Map::new();
                while let Some(k) = a.next_key::<String>()? {
                    if v.contains_key(&k) {
                        return Err(de::Error::custom("duplicate"));
                    }
                    v.insert(k, a.next_value::<Unique>()?.0);
                }
                Ok(Unique(Value::Object(v)))
            }
        }
        d.deserialize_any(V)
    }
}
pub fn decode(raw: &[u8], maximum: usize) -> Result<Value> {
    if raw.len() > maximum {
        return fail(413, "BODY_TOO_LARGE");
    }
    // The first pass rejects duplicate keys and invalid Unicode/nonfinite tokens;
    // the second retains arbitrary-precision Number lexemes (serde JSON mode).
    let mut de = serde_json::Deserializer::from_slice(raw);
    Unique::deserialize(&mut de)?;
    de.end()?;
    Ok(serde_json::from_slice(raw)?)
}
pub fn fields<'a>(
    v: &'a Value,
    required: &[&str],
    optional: &[&str],
) -> Result<&'a Map<String, Value>> {
    let o = v
        .as_object()
        .ok_or_else(|| Error::new(422, "INVALID_FIELDS"))?;
    if required.iter().any(|k| !o.contains_key(*k))
        || o.keys()
            .any(|k| !required.contains(&k.as_str()) && !optional.contains(&k.as_str()))
    {
        return fail(422, "INVALID_FIELDS");
    }
    Ok(o)
}
pub fn text(v: &Value, max: usize, required: bool) -> Result<&str> {
    let s = v.as_str().ok_or_else(|| Error::new(422, "INVALID_TEXT"))?;
    if s.chars().count() > max
        || s.contains('\0')
        || required && quote_core::numbers::trim(s).is_empty()
    {
        return fail(422, "INVALID_TEXT");
    }
    Ok(s)
}
pub fn quote(v: &Value) -> Result<Quote> {
    fields(
        v,
        &["price_version_id", "lines"],
        &["rule_version", "numeric_profile"],
    )?;
    if v.get("rule_version").is_some_and(|x| x != RULE_VERSION)
        || v.get("numeric_profile")
            .is_some_and(|x| x != NUMERIC_PROFILE)
    {
        return fail(409, "PROTOCOL_VERSION_CONFLICT");
    }
    text(&v["price_version_id"], 256, true)?;
    let lines = v["lines"]
        .as_array()
        .ok_or_else(|| Error::new(422, "INVALID_LINES"))?;
    if lines.is_empty() || lines.len() > 1000 {
        return fail(422, "INVALID_LINES");
    }
    for l in lines {
        match l["line_kind"].as_str() {
            Some("normal") => {
                fields(l, &["line_kind", "product_id", "q"], &["h", "w", "name"])?;
                text(&l["product_id"], 256, true)?;
                for k in ["q", "h", "w", "name"] {
                    if let Some(x) = l.get(k) {
                        text(x, 256, false)?;
                    }
                }
            }
            Some("discount") => {
                fields(l, &["line_kind", "percent"], &["name"])?;
                text(&l["percent"], 256, false)?;
                if let Some(x) = l.get("name") {
                    text(x, 256, false)?;
                }
            }
            _ => return fail(422, "INVALID_LINE"),
        }
    }
    Ok(store::decode_quote(v.clone())?)
}
pub fn details(v: &Value) -> Result<Value> {
    fields(v, &["customer", "order_ref", "wechat"], &[])?;
    for x in v.as_object().unwrap().values() {
        text(x, 4096, false)?;
    }
    Ok(v.clone())
}
pub fn prices(v: &Value) -> Result<Prices> {
    fields(v, &["price_version_id", "items"], &[])?;
    text(&v["price_version_id"], 256, true)?;
    let a = v["items"]
        .as_array()
        .ok_or_else(|| Error::new(422, "INVALID_PRICES"))?;
    if a.is_empty() || a.len() > 1000 {
        return fail(422, "INVALID_PRICES");
    }
    for i in a {
        fields(
            i,
            &["product_id", "sale", "cost", "k", "single"],
            &["pricing_mode"],
        )?;
        if i.get("pricing_mode")
            .is_some_and(|v| !matches!(v.as_str(), Some("manual" | "cost_plus")))
        {
            return fail(422, "INVALID_PRICES");
        }
        if !i["single"].is_boolean() {
            return fail(422, "INVALID_PRICES");
        }
        for k in ["product_id", "sale", "cost", "k"] {
            text(&i[k], 256, false)?;
        }
    }
    Ok(serde_json::from_value(v.clone())?)
}
pub fn financial(v: Value, a: &Actor) -> Value {
    let keys = [
        "order_id",
        "note_id",
        "revision",
        "request_id",
        "price_version_id",
        "state",
        "reason",
        "income_cents",
        "job_id",
        "order_revision",
        "kind",
        "format",
    ];
    let private = ["cost_cents", "profit_cents", "ledger_revision"];
    Value::Object(
        v.as_object()
            .map(|o| {
                o.iter()
                    .filter(|(k, _)| {
                        keys.contains(&k.as_str())
                            || a.role == "admin" && private.contains(&k.as_str())
                    })
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect()
            })
            .unwrap_or_default(),
    )
}
pub fn normalized(v: &mut Value, a: &Actor) {
    if a.role != "admin" {
        if let Some(o) = v.as_object_mut() {
            o.retain(|k, _| {
                ["q", "h", "w", "sale", "k", "percent", "single"].contains(&k.as_str())
            });
        }
    }
}
pub fn catalog(p: Prices, a: &Actor) -> Result<Value> {
    let mut v = serde_json::to_value(&p).unwrap();
    for (item, source) in v["items"].as_array_mut().unwrap().iter_mut().zip(&p.items) {
        let unit = quote_core::pricing::unit_sale(source)
            .map_err(|_| Error::new(422, "INVALID_PRICES"))?
            .text();
        item["unit_sale"] = json!(unit);
        if a.role != "admin" {
            item.as_object_mut().unwrap().remove("cost");
            item.as_object_mut().unwrap().remove("pricing_mode");
            if source.pricing_mode.is_some() {
                item["sale"] = item["unit_sale"].clone();
                item["k"] = json!("1");
            }
        }
    }
    if a.role == "admin" {
        v["pricing_mode_version"] = json!("final-unit-v1");
    }
    v["rule_version"] = json!(RULE_VERSION);
    v["numeric_profile"] = json!(NUMERIC_PROFILE);
    Ok(v)
}
pub fn calculated(r: quote_core::models::QuoteResult, a: &Actor) -> Value {
    let lines = r
        .lines
        .as_deref()
        .unwrap_or(&[])
        .iter()
        .map(|l| {
            let mut n = serde_json::to_value(
                l.normalized
                    .iter()
                    .cloned()
                    .collect::<std::collections::BTreeMap<_, _>>(),
            )
            .unwrap();
            normalized(&mut n, a);
            let mut v = financial(l.amounts.cents(), a);
            v["sequence"] = json!(l.sequence);
            v["raw"] = store::legacy_line(&l.raw);
            v["normalized"] = n;
            v["subtotal_before_cents"] = json!(l.subtotal_before.to_string());
            v
        })
        .collect::<Vec<_>>();
    json!({"status":r.status,"price_version_id":r.price_version_id,"lines":lines,"totals":r.totals.map(|t|financial(t.cents(),a)),"issues":r.issues,"warnings":r.warnings})
}
