use super::*;
use rusqlite::{params, OptionalExtension};
impl Local {
    pub(super) fn insert_operation(&self, raw: &Value) -> Result<()> {
        quote_ledger::intake::payload::validate(raw)
            .map_err(|e| DesktopError::new(422, &e.code))?;
        let bytes = canonical(raw)?;
        let (count,size):(i64,i64)=self.c.query_row("SELECT count(*) FILTER(WHERE state NOT IN ('applied','settled')),coalesce(sum(length(raw)),0) FROM local_operations",[],|r|Ok((r.get(0)?,r.get(1)?))).map_err(sql)?;
        if bytes.len() > 262144 || count >= 10000 || size + bytes.len() as i64 > 268435456 {
            return Err(DesktopError::new(413, "LOCAL_ORDER_CAPACITY"));
        }
        self.c
            .execute(
                "INSERT INTO local_operations VALUES(?,?,?,?,?,'pending',NULL,?,?)",
                params![
                    raw["operation_id"].as_str(),
                    raw["order_id"].as_str(),
                    raw["stream_id"].as_str(),
                    number(&raw["device_sequence"])?,
                    self.encode(raw)?,
                    raw["base"]["previous_operation_id"].as_str(),
                    raw["payload"]["customer"]["anchor_order_id"]
                        .as_str()
                        .filter(|id| *id != raw["order_id"].as_str().unwrap_or(""))
                ],
            )
            .map_err(sql)?;
        Ok(())
    }
    pub(crate) fn upload(&self) -> Result<Vec<Value>> {
        let mut q=self.c.prepare("SELECT o.raw FROM local_operations o WHERE o.state='pending' AND (o.previous_id IS NULL OR EXISTS(SELECT 1 FROM local_operations p WHERE p.id=o.previous_id AND p.state IN ('applied','conflict','rejected','settled'))) AND (o.anchor_id IS NULL OR NOT EXISTS(SELECT 1 FROM local_operations a WHERE a.order_id=o.anchor_id AND a.state NOT IN ('applied','settled','conflict','rejected'))) ORDER BY o.sequence,o.id LIMIT 32").map_err(sql)?;
        let rows = q
            .query_map([], |r| r.get::<_, Vec<u8>>(0))
            .map_err(sql)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(sql)?;
        let mut out = Vec::new();
        let mut size = 0;
        for row in rows {
            let raw = self.decode(&row)?;
            if let Some(prev) = raw["base"]["previous_operation_id"].as_str() {
                let state: Option<String> = self
                    .c
                    .query_row(
                        "SELECT state FROM local_operations WHERE id=?",
                        [prev],
                        |r| r.get(0),
                    )
                    .optional()
                    .map_err(sql)?;
                if !state
                    .as_deref()
                    .is_some_and(|s| ["applied", "conflict", "rejected", "settled"].contains(&s))
                {
                    continue;
                }
            }
            if let Some(anchor) = raw["payload"]["customer"]["anchor_order_id"]
                .as_str()
                .filter(|id| *id != raw["order_id"].as_str().unwrap_or(""))
            {
                let waiting:bool=self.c.query_row("SELECT EXISTS(SELECT 1 FROM local_operations WHERE order_id=? AND state NOT IN ('applied','settled','conflict','rejected'))",[anchor],|r|r.get(0)).map_err(sql)?;
                if waiting {
                    continue;
                }
            }
            let bytes = canonical(&raw)?.len();
            if size + bytes > 900000 {
                break;
            }
            size += bytes;
            out.push(raw);
        }
        Ok(out)
    }
    pub(crate) fn receipt_ids(&self) -> Result<Vec<Value>> {
        let mut current = {
            let mut q=self.c.prepare("SELECT id FROM local_operations WHERE state='received' ORDER BY sequence,id LIMIT 16").map_err(sql)?;
            let rows = q
                .query_map([], |r| r.get::<_, String>(0))
                .map_err(sql)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(sql)?;
            rows
        };
        let after = self
            .meta("receipt_cursor")?
            .and_then(|v| v.as_str().map(str::to_owned))
            .unwrap_or_default();
        let rest = {
            let mut q=self.c.prepare("SELECT id FROM local_operations WHERE id>? AND state IN ('waiting_dependency','conflict','rejected') ORDER BY id LIMIT 16").map_err(sql)?;
            let rows = q
                .query_map([after], |r| r.get::<_, String>(0))
                .map_err(sql)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(sql)?;
            rows
        };
        self.put(
            "receipt_cursor",
            &json!(rest.last().cloned().unwrap_or_default()),
        )?;
        current.extend(rest);
        Ok(current.into_iter().map(Value::String).collect())
    }
    pub(crate) fn receipts(&self, values: &Value) -> Result<()> {
        self.transaction(||{
        for r in values.as_array().ok_or_else(||fault("INVALID_RECEIPT"))?{
            let id=identifier(&r["operation_id"])?;
            let raw:Vec<u8>=self.c.query_row("SELECT raw FROM local_operations WHERE id=?",[id],|r|r.get(0)).map_err(sql)?;let raw=self.decode(&raw)?;
            let state=r["state"].as_str().ok_or_else(||fault("INVALID_RECEIPT"))?;
            if state=="not_found"{self.c.execute("UPDATE local_operations SET state='pending' WHERE id=? AND state NOT IN ('applied','settled','conflict','rejected')",[id]).map_err(sql)?;continue}
            if r["content_sha256"]!=raw["content_sha256"]||!["received","waiting_dependency","applied","conflict","rejected"].contains(&state){return Err(fault("INVALID_RECEIPT"))}
            let current:String=self.c.query_row("SELECT state FROM local_operations WHERE id=?",[id],|r|r.get(0)).map_err(sql)?;
            if ["applied","settled"].contains(&current.as_str()){continue}
            let state=if r.get("resolution").is_some(){"settled"}else{state};
            self.c.execute("UPDATE local_operations SET state=?,receipt=? WHERE id=?",params![state,self.encode(r)?,id]).map_err(sql)?;
            if state=="applied"||state=="settled"{
                let source=raw["order_id"].as_str().unwrap();
                if r["resolution"]=="merged"&&r["result"]["order_id"]!=raw["order_id"]{self.put(&format!("alias:{source}"),&r["result"]["order_id"])?;}
                self.promote(source)?;
            }
        }Ok(())
    })
    }
    pub(crate) fn receive_order(&self, mut view: Value) -> Result<()> {
        let ctx = self.context()?;
        let id = identifier(&view["order_id"])?.to_owned();
        if ctx["binding"]["role"] != "admin" && view["owner_id"] != ctx["binding"]["subject"] {
            return Err(DesktopError::new(403, "LOCAL_OWNER_MISMATCH"));
        }
        number(&view["revision"])?;
        public(&mut view, &ctx);
        self.transaction(||{
            let existing:Option<Vec<u8>>=self.c.query_row("SELECT confirmed FROM local_orders WHERE id=?",[&id],|r|r.get(0)).optional().map_err(sql)?.flatten();
            if let Some(raw)=existing {let previous=self.decode(&raw)?;if previous["deleted"]==true || number(&previous["revision"])? > number(&view["revision"])? {return Ok(());}}
            self.queue_history(&view)?;
            let pending:bool=self.c.query_row("SELECT EXISTS(SELECT 1 FROM local_operations WHERE order_id=? AND state NOT IN ('applied','settled'))",[&id],|r|r.get(0)).map_err(sql)?;
            let bytes=self.encode(&view)?;let rev=number(&view["revision"])?;
            self.c.execute("INSERT INTO local_orders VALUES(?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET confirmed=excluded.confirmed",params![id,bytes,bytes,rev]).map_err(sql)?;
            if !pending || view["deleted"] == true {self.c.execute("UPDATE local_orders SET working=?,revision=?,last_operation=NULL WHERE id=?",params![bytes,rev,id]).map_err(sql)?;}
            Ok(())
        })
    }
    fn promote(&self, id: &str) -> Result<()> {
        let pending:bool=self.c.query_row("SELECT EXISTS(SELECT 1 FROM local_operations WHERE order_id=? AND state NOT IN ('applied','settled'))",[id],|r|r.get(0)).map_err(sql)?;
        if !pending {
            let raw: Option<Vec<u8>> = self
                .c
                .query_row("SELECT confirmed FROM local_orders WHERE id=?", [id], |r| {
                    r.get(0)
                })
                .optional()
                .map_err(sql)?
                .flatten();
            if let Some(raw) = raw {
                let view = self.decode(&raw)?;
                let last:Option<Vec<u8>>=self.c.query_row("SELECT receipt FROM local_operations WHERE order_id=? AND state IN ('applied','settled') ORDER BY sequence DESC LIMIT 1",[id],|r|r.get(0)).optional().map_err(sql)?.flatten();
                if last.map(|r| self.decode(&r)).transpose()?.is_none_or(|r| {
                    number(&r["result"]["revision"]).unwrap_or(i64::MAX)
                        <= number(&view["revision"]).unwrap_or(0)
                }) {
                    self.c.execute("UPDATE local_orders SET working=?,revision=?,last_operation=NULL WHERE id=?",params![raw,number(&view["revision"])?,id]).map_err(sql)?;
                }
            }
        }
        Ok(())
    }
    pub(crate) fn output_revision(&self, id: &str, expected: &str) -> Result<String> {
        let order = self.order(id)?;
        let pending:bool=self.c.query_row("SELECT EXISTS(SELECT 1 FROM local_operations WHERE order_id=? AND state NOT IN ('applied','settled'))",[id],|r|r.get(0)).map_err(sql)?;
        if pending || order["revision"] != expected {
            return Err(fault("ORDER_CONFIRMATION_REQUIRED"));
        }
        self.confirmed_revision(id)?
            .ok_or_else(|| fault("ORDER_CONFIRMATION_REQUIRED"))
    }
    pub(crate) fn confirmed_revision(&self, id: &str) -> Result<Option<String>> {
        let raw: Option<Vec<u8>> = self
            .c
            .query_row("SELECT confirmed FROM local_orders WHERE id=?", [id], |r| {
                r.get(0)
            })
            .optional()
            .map_err(sql)?
            .flatten();
        raw.map(|v| {
            self.decode(&v)
                .map(|v| v["revision"].as_str().unwrap_or("").into())
        })
        .transpose()
    }
}
