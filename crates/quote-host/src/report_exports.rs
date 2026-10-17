//! One ledger read snapshot, bounded in-memory chunks and atomically queued files.
//! Temporary SQLite staging allows the final part count without retaining the
//! entire report in RAM or modifying any immutable published payload.
use crate::{auth::Auth, fail, outputs::Outputs, Error, Result};
use quote_ledger::store::{self, Actor};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use time::{format_description::well_known::Rfc3339, OffsetDateTime, UtcOffset};
const BUDGET: usize = 2 * 1024 * 1024 - 65536;
fn local_day(order: &Value) -> Result<String> {
    let t = OffsetDateTime::parse(
        order["created_at"]
            .as_str()
            .ok_or_else(|| Error::new(422, "INVALID_OUTPUT_REQUEST"))?,
        &Rfc3339,
    )
    .map_err(|_| Error::new(422, "INVALID_OUTPUT_REQUEST"))?
    .to_offset(UtcOffset::from_hms(8, 0, 0).unwrap());
    Ok(format!(
        "{:04}-{:02}-{:02}",
        t.year(),
        t.month() as u8,
        t.day()
    ))
}
struct Batch<'a> {
    data: &'a Value,
    revision: &'a Value,
    at: String,
    key: &'a str,
}
impl Batch<'_> {
    fn payload(&self, orders: &[Value], part: usize, count: usize, job: &str) -> Result<Value> {
        let from = orders
            .first()
            .map(local_day)
            .transpose()?
            .unwrap_or_else(|| self.data["from"].as_str().unwrap().into());
        let to = orders
            .last()
            .map(local_day)
            .transpose()?
            .unwrap_or_else(|| self.data["to"].as_str().unwrap().into());
        Ok(
            json!({"format":"777-output-v1","presentation":"monthly-v1","generated_at":self.at,"job_id":job,"kind":"excel_period","orders":orders,"range":{"from":self.data["from"],"to":self.data["to"],"timezone":"Asia/Shanghai"},"ledger_revision":self.revision,"batch":{"id":self.key,"part":part,"count":count,"from":from,"to":to,"order_count":orders.len()}}),
        )
    }
    fn stage(&self, c: &Connection, orders: Vec<Value>, next: &mut usize) -> Result<()> {
        let payload = self.payload(&orders, *next, u32::MAX as usize, self.key)?;
        let rendered = quote_excel::write::write(&payload);
        let split = match rendered {
            Ok(bytes) => bytes.len() > quote_excel::OUTPUT_LIMIT - 65536,
            Err(e)
                if matches!(
                    e.code.as_str(),
                    "OUTPUT_SNAPSHOT_TOO_LARGE" | "OUTPUT_TOO_LARGE"
                ) =>
            {
                true
            }
            Err(e) => return Err(e.into()),
        };
        if split {
            if orders.len() <= 1 {
                return fail(413, "OUTPUT_SINGLE_ORDER_TOO_LARGE");
            }
            // Prefer month boundaries, then divide only between whole orders.
            let first = local_day(&orders[0])?;
            let boundary = orders.iter().enumerate().skip(1).find_map(|(i, o)| {
                local_day(o)
                    .ok()
                    .filter(|d| d[..7] != first[..7])
                    .map(|_| i)
            });
            if boundary.is_some() {
                self.months(c, orders, next)?;
            } else {
                let mut left = orders;
                let right = left.split_off(left.len() / 2);
                self.stage(c, left, next)?;
                self.stage(c, right, next)?;
            }
        } else {
            c.execute(
                "INSERT INTO report_parts VALUES(?,?)",
                params![*next as i64, serde_json::to_string(&orders)?],
            )?;
            *next += 1;
        }
        Ok(())
    }
    fn months(&self, c: &Connection, orders: Vec<Value>, next: &mut usize) -> Result<()> {
        let mut month = String::new();
        let mut chunk = vec![];
        for order in orders {
            let day = local_day(&order)?;
            if !chunk.is_empty() && month != day[..7] {
                self.stage(c, std::mem::take(&mut chunk), next)?;
            }
            month = day[..7].into();
            chunk.push(order);
        }
        if !chunk.is_empty() {
            self.stage(c, chunk, next)?;
        }
        Ok(())
    }
}
pub fn enqueue(
    outputs: &Outputs,
    actor: &Actor,
    data: &Value,
    revision: &Value,
    orders: impl Iterator<Item = Result<Value>>,
) -> Result<Value> {
    enqueue_with_budget(outputs, actor, data, revision, orders, BUDGET)
}
fn enqueue_with_budget(
    outputs: &Outputs,
    actor: &Actor,
    data: &Value,
    revision: &Value,
    orders: impl Iterator<Item = Result<Value>>,
    budget: usize,
) -> Result<Value> {
    Auth::admin(actor)?;
    let key = crate::protocol::text(&data["request_id"], 36, true)?;
    store::id(key)?;
    let mut fp = data.clone();
    fp["actor"] = json!(actor.subject);
    fp["role"] = json!(actor.role);
    let fp = store::hash(store::encoded(&fp));
    if let Some(receipt) = outputs.receipt(actor, key, Some(&fp))? {
        return Ok(receipt);
    }
    let c = outputs.connection()?;
    // Serialize writers and recheck deduplication after acquiring the lock.
    c.execute_batch("PRAGMA temp_store=FILE; BEGIN IMMEDIATE")?;
    if let Some(receipt) = outputs.receipt(actor, key, Some(&fp))? {
        return Ok(receipt);
    }
    if c.query_row(
        "SELECT count(*) FROM jobs WHERE state IN ('queued','running')",
        [],
        |r| r.get::<_, i64>(0),
    )? >= 64
    {
        return fail(429, "OUTPUT_QUEUE_FULL");
    }
    c.execute_batch(
        "CREATE TEMP TABLE report_parts(part INTEGER PRIMARY KEY,orders_json TEXT NOT NULL)",
    )?;
    let batch = Batch {
        data,
        revision,
        at: store::now(),
        key,
    };
    let mut chunk = vec![];
    let mut size = 0;
    let mut next = 1;
    let mut split = false;
    let mut month = String::new();
    for order in orders {
        let order = order?;
        let bytes = store::encoded(&order).len();
        let day = local_day(&order)?;
        if !split && !chunk.is_empty() && size + bytes > budget {
            split = true;
            // Flush completed months, retaining the last month so its remaining
            // orders can fill one file before a same-month split is necessary.
            let boundary = chunk
                .iter()
                .position(|o| local_day(o).is_ok_and(|d| d[..7] == month))
                .unwrap_or(0);
            if boundary > 0 {
                let tail = chunk.split_off(boundary);
                batch.months(&c, std::mem::replace(&mut chunk, tail), &mut next)?;
                size = chunk.iter().map(|o| store::encoded(o).len()).sum();
            }
        }
        if split && !chunk.is_empty() && (size + bytes > budget || month != day[..7]) {
            batch.stage(&c, std::mem::take(&mut chunk), &mut next)?;
            size = 0;
        }
        month = day[..7].into();
        size += bytes;
        chunk.push(order);
    }
    if split {
        batch.months(&c, chunk, &mut next)?;
    } else {
        batch.stage(&c, chunk, &mut next)?;
    }
    let count = next - 1;
    let mut st = c.prepare("SELECT part,orders_json FROM report_parts ORDER BY part")?;
    let mut rows = st.query([])?;
    while let Some(row) = rows.next()? {
        let part = row.get::<_, i64>(0)? as usize;
        let orders: Vec<Value> = serde_json::from_str(&row.get::<_, String>(1)?)?;
        let job = if part == 1 {
            key.to_string()
        } else {
            store::uid()?
        };
        let payload = batch.payload(&orders, part, count, &job)?;
        let raw = store::encoded(&payload);
        // Validate the exact final metadata as well; queue is still atomic.
        quote_excel::write::write(&payload)?;
        c.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,'queued',0,NULL,NULL,NULL,NULL,NULL,?)",
            params![
                job,
                actor.subject,
                actor.role,
                key,
                "excel_period",
                raw,
                store::hash(store::encoded(&payload)),
                batch.at
            ],
        )?;
        c.execute(
            "INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,'enqueue',?,?)",
            params![job, actor.subject, batch.at],
        )?;
    }
    let receipt = json!({"request_id":key,"job_id":key,"batch_id":key,"part_count":count,"kind":"excel_period","format":"777-output-v1","state":"queued"});
    c.execute(
        "INSERT INTO receipts VALUES(?,?,?,?)",
        params![key, actor.subject, fp, store::encoded(&receipt)],
    )?;
    c.execute_batch("COMMIT")?;
    Ok(receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture {
        root: std::path::PathBuf,
        outputs: Outputs,
        actor: Actor,
    }
    impl Fixture {
        fn new() -> Self {
            let root =
                std::env::temp_dir().join(format!("777-report-batch-{}", store::uid().unwrap()));
            std::fs::create_dir_all(&root).unwrap();
            let outputs =
                Outputs::create(&root.join("outputs.sqlite3"), &store::uid().unwrap()).unwrap();
            Self {
                root,
                outputs,
                actor: Actor {
                    subject: store::uid().unwrap(),
                    role: "admin".into(),
                },
            }
        }
        fn data(&self) -> Value {
            json!({"request_id":store::uid().unwrap(),"kind":"excel_period","from":"2026-01-01","to":"2026-12-31"})
        }
        fn payloads(&self) -> Vec<Value> {
            let c = self.outputs.connection().unwrap();
            let mut st=c.prepare("SELECT payload_json FROM jobs ORDER BY CAST(json_extract(payload_json,'$.batch.part') AS INTEGER)").unwrap();
            st.query_map([], |r| r.get::<_, String>(0))
                .unwrap()
                .map(|r| serde_json::from_str(&r.unwrap()).unwrap())
                .collect()
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }
    fn order(n: usize, date: &str, note_bytes: usize) -> Value {
        json!({"order_id":format!("order-{n}"),"created_at":date,"state":if n==2{"void"}else{"active"},"revision":1,"details":{"customer":"客户","wechat":"00001","order_ref":format!("0000{n}")},"income_cents":"1001","cost_cents":"500","profit_cents":"501","lines":[{"raw":{"line_kind":"normal","product_id":"商品","name":""},"normalized":{"q":"1","sale":"10.01"},"income_cents":"1001"}],"notes":[{"body":"x".repeat(note_bytes),"created_at":date}]})
    }
    #[test]
    fn oversized_report_splits_whole_orders_by_beijing_month_with_one_snapshot_and_receipt() {
        let f = Fixture::new();
        let data = f.data();
        let orders = vec![
            order(0, "2026-10-31T15:59:59Z", 800000),
            order(1, "2026-10-31T16:00:00Z", 800000),
            order(2, "2026-11-02T00:00:00Z", 800000),
            order(3, "2026-11-02T00:00:01Z", 800000),
        ];
        let r = enqueue(
            &f.outputs,
            &f.actor,
            &data,
            &json!(17),
            orders.clone().into_iter().map(Ok),
        )
        .unwrap();
        assert!(r["part_count"].as_u64().unwrap() >= 3);
        let parts = f.payloads();
        let mut seen = std::collections::HashSet::new();
        let mut income = 0;
        for (i, p) in parts.iter().enumerate() {
            assert_eq!(p["batch"]["part"], i + 1);
            assert_eq!(p["batch"]["count"], parts.len());
            assert_eq!(p["ledger_revision"], 17);
            assert_eq!(p["generated_at"], parts[0]["generated_at"]);
            assert!(store::encoded(p).len() <= 2 * 1024 * 1024);
            let raw = quote_excel::write::write(p).unwrap();
            assert!(raw.len() <= quote_excel::OUTPUT_LIMIT);
            let read = quote_excel::read::read(&raw).unwrap();
            assert!(read.sheets.iter().any(|s| s.name == "分批说明"));
            let mut monthly_sum = 0i64;
            for sheet in read.sheets.iter().filter(|s| s.name.contains('年')) {
                // Sum only the month-total rows in each actual rendered workbook.
                for cell in &sheet.cells {
                    if cell.value.as_deref() == Some("本月有效订单合计") {
                        let row = cell.row;
                        let amount = sheet
                            .cells
                            .iter()
                            .find(|c| c.row == row && c.column == 14)
                            .unwrap();
                        monthly_sum += amount
                            .value
                            .as_ref()
                            .unwrap()
                            .replace('.', "")
                            .parse::<i64>()
                            .unwrap();
                    }
                }
            }
            let expected: i64 = p["orders"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|o| o["state"] != "void")
                .map(|_| 1001)
                .sum();
            assert_eq!(monthly_sum, expected);
            for o in p["orders"].as_array().unwrap() {
                assert!(seen.insert(o["order_id"].as_str().unwrap().to_owned()));
                if o["state"] != "void" {
                    income += 1001;
                }
            }
        }
        assert_eq!(seen.len(), orders.len());
        assert_eq!(income, 3003);
        assert_eq!(parts[0]["batch"]["to"], "2026-10-31");
        assert_eq!(parts[1]["batch"]["from"], "2026-11-01");
        assert_eq!(parts[1]["batch"]["order_count"], 2);
        // Repeating the request reads the original receipt even with a later ledger revision.
        assert_eq!(
            enqueue(&f.outputs, &f.actor, &data, &json!(99), std::iter::empty()).unwrap(),
            r
        );
        assert_eq!(f.payloads().len(), parts.len());
        let mut changed = data.clone();
        changed["to"] = json!("2026-11-30");
        assert!(enqueue(
            &f.outputs,
            &f.actor,
            &changed,
            &json!(99),
            std::iter::empty()
        )
        .is_err());
    }
    #[test]
    fn small_multimonth_and_empty_reports_remain_one_file_and_failures_rollback() {
        let f = Fixture::new();
        let r = enqueue(
            &f.outputs,
            &f.actor,
            &f.data(),
            &json!(1),
            vec![
                order(0, "2026-09-01T00:00:00Z", 0),
                order(1, "2026-10-01T00:00:00Z", 0),
            ]
            .into_iter()
            .map(Ok),
        )
        .unwrap();
        assert_eq!(r["part_count"], 1);
        let r = enqueue(
            &f.outputs,
            &f.actor,
            &f.data(),
            &json!(1),
            std::iter::empty(),
        )
        .unwrap();
        assert_eq!(r["part_count"], 1);
        let before = f.payloads().len();
        let data = f.data();
        let r = enqueue(
            &f.outputs,
            &f.actor,
            &data,
            &json!(1),
            vec![
                Ok(order(3, "2026-10-01T00:00:00Z", 1500000)),
                Ok(order(4, "2026-10-02T00:00:00Z", 1500000)),
                Err(Error::new(503, "TEST_READ_ERROR")),
            ]
            .into_iter(),
        );
        assert!(r.is_err());
        assert_eq!(f.payloads().len(), before);
        assert!(!f
            .outputs
            .has_request(data["request_id"].as_str().unwrap())
            .unwrap());
        let error = enqueue(
            &f.outputs,
            &f.actor,
            &f.data(),
            &json!(1),
            std::iter::once(Ok(order(5, "2026-10-01T00:00:00Z", 3 * 1024 * 1024))),
        )
        .unwrap_err();
        assert_eq!(error.code, "OUTPUT_SINGLE_ORDER_TOO_LARGE");
        assert_eq!(f.payloads().len(), before);
    }
    #[test]
    fn batch_over_one_hundred_parts_is_pageable_and_one_failed_part_retries_without_duplication() {
        let f = Fixture::new();
        let data = f.data();
        let r = enqueue_with_budget(
            &f.outputs,
            &f.actor,
            &data,
            &json!(1),
            (0..105).map(|n| Ok(order(n, "2026-10-01T00:00:00Z", 0))),
            1,
        )
        .unwrap();
        assert_eq!(r["part_count"], 105);
        let first = f.outputs.listing_page(&f.actor, 0).unwrap();
        let second = f.outputs.listing_page(&f.actor, 100).unwrap();
        assert_eq!(first["total"], 105);
        assert_eq!(first["jobs"].as_array().unwrap().len(), 100);
        assert_eq!(second["jobs"].as_array().unwrap().len(), 5);
        let ids: std::collections::HashSet<_> = first["jobs"]
            .as_array()
            .unwrap()
            .iter()
            .chain(second["jobs"].as_array().unwrap())
            .map(|j| j["job_id"].as_str().unwrap())
            .collect();
        assert_eq!(ids.len(), 105);
        assert_eq!(second["jobs"][0]["batch"]["part"], 101);
        let sales = Actor {
            subject: f.actor.subject.clone(),
            role: "sales".into(),
        };
        assert_eq!(f.outputs.listing_page(&sales, 0).unwrap()["total"], 0);
        let job = second["jobs"][0]["job_id"].as_str().unwrap();
        let before = f.payloads();
        let c = f.outputs.connection().unwrap();
        c.execute("UPDATE jobs SET state='done'", []).unwrap();
        c.execute("UPDATE jobs SET state='failed' WHERE job_id=?", [job])
            .unwrap();
        drop(c);
        f.outputs
            .retry(&f.actor, job, &store::uid().unwrap())
            .unwrap();
        assert_eq!(f.outputs.status(&f.actor, job).unwrap()["state"], "queued");
        assert_eq!(f.payloads(), before);
        assert!(f.outputs.status(&sales, job).is_err());
    }
}
