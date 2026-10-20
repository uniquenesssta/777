//! Read-only, revision-bound collection; large reports stage on local temporary SQLite.
use super::*;
use rusqlite::Connection as Sqlite;
use time::{format_description::well_known::Rfc3339, OffsetDateTime, UtcOffset};
fn error() -> DesktopError {
    DesktopError::new(422, "INVALID_ANALYTICS_QUERY")
}
fn day(order: &Value) -> Result<String> {
    let t = OffsetDateTime::parse(order["created_at"].as_str().ok_or_else(error)?, &Rfc3339)
        .map_err(|_| error())?
        .to_offset(UtcOffset::from_hms(8, 0, 0).unwrap());
    Ok(format!(
        "{:04}-{:02}-{:02}",
        t.year(),
        t.month() as u8,
        t.day()
    ))
}
fn sql(_: rusqlite::Error) -> DesktopError {
    DesktopError::new(503, "LOCAL_OUTPUT_HISTORY_UNAVAILABLE")
}
fn part(orders: &[Value], from: &str, to: &str, id: &str) -> Value {
    json!({"format":"777-output-v1","presentation":"monthly-v1","generated_at":quote_ledger::store::now(),"job_id":id,"kind":"excel_period","orders":orders,"range":{"from":from,"to":to,"timezone":"Asia/Shanghai"}})
}
fn stage(c: &Sqlite, orders: Vec<Value>, from: &str, to: &str, id: &str) -> Result<()> {
    let result = quote_excel::write::write(&part(&orders, from, to, id));
    match result {
        Ok(raw) if raw.len() < quote_excel::OUTPUT_LIMIT - 65536 => {
            c.execute(
                "INSERT INTO parts(data) VALUES(?)",
                [serde_json::to_string(&orders).map_err(|_| error())?],
            )
            .map_err(sql)?;
            Ok(())
        }
        Err(e)
            if !matches!(
                e.code.as_str(),
                "OUTPUT_SNAPSHOT_TOO_LARGE" | "OUTPUT_TOO_LARGE"
            ) =>
        {
            Err(DesktopError::new(422, &e.code))
        }
        _ => {
            if orders.len() < 2 {
                return Err(DesktopError::new(413, "OUTPUT_SINGLE_ORDER_TOO_LARGE"));
            }
            let month = day(&orders[0])?;
            let pivot = orders
                .iter()
                .position(|o| day(o).is_ok_and(|d| d[..7] != month[..7]))
                .unwrap_or(orders.len() / 2);
            let mut left = orders;
            let right = left.split_off(pivot);
            stage(c, left, from, to, id)?;
            stage(c, right, from, to, id)
        }
    }
}
impl Desktop {
    pub(super) async fn create_local_report(&mut self, from: &str, to: &str) -> Result<Value> {
        self.admin()?;
        crate::local_outputs::root(&self.store)?;
        for d in [from, to] {
            OffsetDateTime::parse(&format!("{d}T00:00:00Z"), &Rfc3339).map_err(|_| error())?;
        }
        if from > to {
            return Err(error());
        }
        let temp = Sqlite::open("").map_err(sql)?;
        temp.execute_batch("CREATE TABLE orders(day TEXT,id TEXT PRIMARY KEY,data TEXT);CREATE TABLE parts(data TEXT);").map_err(sql)?;
        let mut offset = 0u64;
        let mut view = String::new();
        loop {
            let path = report_path(offset, &view);
            let page = self.request("GET", &path, None).await?;
            if view.is_empty() {
                view = page["view"]
                    .as_str()
                    .filter(|v| !v.is_empty())
                    .ok_or_else(error)?
                    .into();
            }
            let rows = page["orders"].as_array().ok_or_else(error)?;
            for row in rows {
                let d = day(row)?;
                if d.as_str() < from || d.as_str() > to {
                    continue;
                }
                let id = identifier(row["order_id"].as_str().ok_or_else(error)?)?;
                let order = self
                    .request("GET", &format!("/v1/orders/{id}"), None)
                    .await?;
                if order["revision"] != row["revision"] {
                    return Err(DesktopError::new(409, "QUERY_VIEW_CHANGED"));
                }
                temp.execute(
                    "INSERT INTO orders VALUES(?,?,?)",
                    rusqlite::params![d, id, order.to_string()],
                )
                .map_err(sql)?;
            }
            offset += rows.len() as u64;
            if offset >= page["total"].as_u64().ok_or_else(error)? {
                break;
            }
            if rows.is_empty() {
                return Err(error());
            }
        }
        // A change anywhere during collection invalidates this report; no file has been published.
        self.request("GET", &report_path(0, &view), None).await?;
        let batch = new_id()?;
        let mut q = temp
            .prepare("SELECT data FROM orders ORDER BY day,id")
            .map_err(sql)?;
        let mut rows = q.query([]).map_err(sql)?;
        let mut chunk = vec![];
        let mut bytes = 0;
        while let Some(row) = rows.next().map_err(sql)? {
            let raw: String = row.get(0).map_err(sql)?;
            if !chunk.is_empty() && bytes + raw.len() > 1500000 {
                stage(&temp, std::mem::take(&mut chunk), from, to, &batch)?;
                bytes = 0;
            }
            bytes += raw.len();
            chunk.push(serde_json::from_str(&raw).map_err(|_| error())?);
        }
        if !chunk.is_empty() || offset == 0 {
            stage(&temp, chunk, from, to, &batch)?;
        }
        let count: i64 = temp
            .query_row("SELECT count(*) FROM parts", [], |r| r.get(0))
            .map_err(sql)?;
        // Empty selected range still produces a readable workbook.
        if count == 0 {
            stage(&temp, vec![], from, to, &batch)?;
        }
        let count: i64 = temp
            .query_row("SELECT count(*) FROM parts", [], |r| r.get(0))
            .map_err(sql)?;
        let mut q = temp
            .prepare("SELECT rowid,data FROM parts ORDER BY rowid")
            .map_err(sql)?;
        let mut rows = q.query([]).map_err(sql)?;
        while let Some(row) = rows.next().map_err(sql)? {
            let n: i64 = row.get(0).map_err(sql)?;
            let raw: String = row.get(1).map_err(sql)?;
            let orders: Vec<Value> = serde_json::from_str(&raw).map_err(|_| error())?;
            let id = new_id()?;
            let mut payload = part(&orders, from, to, &id);
            payload["batch"] = json!({"id":batch,"part":n,"count":count,"from":orders.first().map(day).transpose()?.unwrap_or(from.into()),"to":orders.last().map(day).transpose()?.unwrap_or(to.into()),"order_count":orders.len()});
            self.publish_local_export(&payload)?;
        }
        Ok(json!({"batch_id":batch,"part_count":count}))
    }
}
fn report_path(offset: u64, view: &str) -> String {
    let mut url = reqwest::Url::parse("https://localhost/v1/orders").unwrap();
    url.query_pairs_mut()
        .append_pair("limit", "200")
        .append_pair("offset", &offset.to_string())
        .append_pair("view", view);
    format!("{}?{}", url.path(), url.query().unwrap())
}
#[cfg(test)]
#[path = "local_reports_checks.rs"]
mod checks;
