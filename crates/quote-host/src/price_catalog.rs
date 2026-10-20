//! Price publication metadata shared by online catalogs and signed offline leases.
use crate::{protocol, Result};
use quote_ledger::store::{self, Actor};
use rusqlite::Connection;
use serde_json::Value;
#[cfg(test)]
mod tests;

pub(crate) fn active(c: &Connection, actor: &Actor) -> Result<Value> {
    let prices = store::active_prices(c)?;
    let id = prices.price_version_id.as_str().unwrap_or("");
    let published: String = c.query_row(
        "SELECT created_at FROM price_versions WHERE price_id=?",
        [id],
        |r| r.get(0),
    )?;
    let mut value = protocol::catalog(prices, actor)?;
    let sequence =
        publication_sequence(c, &published, value["price_version_id"].as_str().unwrap())?;
    value["published_at"] = Value::String(published);
    value["publication_sequence"] = Value::String(sequence.to_string());
    Ok(value)
}

fn publication_sequence(c: &Connection, published: &str, id: &str) -> Result<i64> {
    Ok(c.query_row(
        "SELECT count(*) FROM price_versions p JOIN requests r
         ON r.operation='publish_prices' AND json_extract(r.result_json,'$.price_version_id')=p.price_id
         WHERE date(p.created_at,'+8 hours')=date(?1,'+8 hours')
         AND r.ledger_revision <= (SELECT ledger_revision FROM requests
           WHERE operation='publish_prices' AND json_extract(result_json,'$.price_version_id')=?2)",
        rusqlite::params![published, id],
        |r| r.get(0),
    )?)
}
