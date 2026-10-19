use crate::{editing, Result};
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::Value;
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Line {
    pub line_id: String,
    pub raw: Value,
    pub price_version_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Order {
    pub order_id: String,
    pub owner_id: String,
    pub revision: i64,
    pub price_version_id: String,
    pub created_at: String,
    pub details: Value,
    pub lines: Vec<Line>,
    pub state: String,
    pub customer_id: Option<String>,
}
impl Order {
    pub fn from_snapshot(snapshot: &Value) -> Result<Self> {
        let o = &snapshot["order"];
        Ok(Self {
            order_id: o["order_id"].as_str().unwrap().into(),
            owner_id: o["owner_id"].as_str().unwrap().into(),
            revision: o["revision"].as_i64().unwrap(),
            price_version_id: o["price_id"].as_str().unwrap().into(),
            created_at: o["created_at"].as_str().unwrap().into(),
            details: serde_json::from_str(o["details_json"].as_str().unwrap())?,
            lines: snapshot["lines"]
                .as_array()
                .unwrap()
                .iter()
                .map(|l| {
                    Ok(Line {
                        line_id: l["line_id"].as_str().unwrap().into(),
                        raw: serde_json::from_str(l["raw_json"].as_str().unwrap())?,
                        price_version_id: l["price_version_id"]
                            .as_str()
                            .unwrap_or(o["price_id"].as_str().unwrap())
                            .into(),
                    })
                })
                .collect::<Result<Vec<_>>>()?,
            state: o["state"].as_str().unwrap().into(),
            customer_id: o["customer_id"].as_str().map(str::to_owned),
        })
    }
    pub fn read(c: &Connection, id: &str) -> Result<Self> {
        Self::from_snapshot(&editing::snapshot(c, id)?)
    }
}
