use super::*;
use rusqlite::params;
impl Local {
    pub(super) fn history(&self, before: &Value, after: &Value) -> Result<()> {
        let mut before = before.clone();
        let mut after = after.clone();
        before
            .as_object_mut()
            .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
            .remove("history");
        after
            .as_object_mut()
            .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
            .remove("history");
        self.c
            .execute(
                "INSERT INTO local_history VALUES(?,?,?,?)",
                params![
                    before["order_id"].as_str(),
                    number(&before["revision"])?,
                    self.encode(&before)?,
                    self.encode(&after)?
                ],
            )
            .map_err(sql)?;
        Ok(())
    }
    pub(crate) fn history_summary(&self, id: &str) -> Result<Vec<Value>> {
        let mut q = self
            .c
            .prepare("SELECT before FROM local_history WHERE order_id=? ORDER BY revision DESC")
            .map_err(sql)?;
        let rows = q
            .query_map([id], |r| r.get::<_, Vec<u8>>(0))
            .map_err(sql)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(sql)?;
        rows.into_iter().map(|b|{let b=self.decode(&b)?;let mut v=json!({"revision":b["revision"],"created_at":b["created_at"],"details":b["details"],"income_cents":b["income_cents"]});for k in ["cost_cents","profit_cents"]{if let Some(x)=b.get(k){v[k]=x.clone()}}Ok(v)}).collect()
    }
    pub(crate) fn changes(&self, id: &str, revision: &str) -> Result<Value> {
        self.order(id)?;
        if let Some(v) = self.meta(&format!("diff:{id}:{revision}"))? {
            return Ok(v);
        }
        let confirmed:bool=self.c.query_row("SELECT EXISTS(SELECT 1 FROM local_orders o WHERE o.id=? AND o.confirmed IS NOT NULL AND o.last_operation IS NULL)",[id],|r|r.get(0)).map_err(sql)?;
        if confirmed {
            return Err(DesktopError::new(404, "NOT_FOUND"));
        }
        use rusqlite::OptionalExtension;
        let row: Option<(Vec<u8>, Vec<u8>)> = self
            .c
            .query_row(
                "SELECT before,after FROM local_history WHERE order_id=? AND revision=?",
                params![id, revision],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(sql)?;
        let (a, b) = row.ok_or_else(|| DesktopError::new(404, "NOT_FOUND"))?;
        let a = self.decode(&a)?;
        let b = self.decode(&b)?;
        let mut changes = Vec::new();
        for (k, label) in [
            ("customer", "客户 / 淘宝 ID"),
            ("order_ref", "订单号"),
            ("wechat", "微信号"),
        ] {
            diff(
                &mut changes,
                "客户信息",
                label,
                &a["details"][k],
                &b["details"][k],
                "text",
            );
        }
        for (k, label) in [
            ("income_cents", "金额"),
            ("cost_cents", "成本"),
            ("profit_cents", "利润"),
        ] {
            diff(&mut changes, "订单金额", label, &a[k], &b[k], "money");
        }
        let left = a["lines"]
            .as_array()
            .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?;
        let right = b["lines"]
            .as_array()
            .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?;
        for n in 0..left.len().max(right.len()) {
            let a = left.get(n).unwrap_or(&Value::Null);
            let b = right.get(n).unwrap_or(&Value::Null);
            for k in ["product_id", "q", "h", "w", "percent", "name"] {
                diff(
                    &mut changes,
                    &format!("商品 {}", n + 1),
                    k,
                    &a["raw"][k],
                    &b["raw"][k],
                    "text",
                );
            }
        }
        let mut result = json!({"revision":revision,"to_revision":b["revision"],"created_at":b["created_at"],"changes":changes});
        public(&mut result, &self.context()?);
        Ok(result)
    }
}
fn diff(out: &mut Vec<Value>, section: &str, field: &str, a: &Value, b: &Value, format: &str) {
    if a != b {
        out.push(json!({"section":section,"field":field,"before":a,"after":b,"format":format}));
    }
}
