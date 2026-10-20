//! Bounded durable history fragments; publish a diff only after the complete hash matches.
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use rusqlite::{params, OptionalExtension};
impl Local {
    pub(crate) fn history_task(&self) -> Result<Option<(String, String)>> {
        self.c.query_row("SELECT order_id,revision FROM local_diff_queue WHERE NOT EXISTS(SELECT 1 FROM local_meta m WHERE m.key='diff:'||order_id||':'||revision) ORDER BY order_id,revision LIMIT 1",[],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(sql)
    }
    pub(super) fn queue_history(&self, view: &Value) -> Result<()> {
        for h in view["history"]
            .as_array()
            .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
        {
            self.c
                .execute(
                    "INSERT INTO local_diff_queue VALUES(?,?) ON CONFLICT DO NOTHING",
                    params![view["order_id"].as_str(), h["revision"].as_str()],
                )
                .map_err(sql)?;
        }
        Ok(())
    }
    pub(crate) fn history_part(&self, id: &str, revision: &str, part: &Value) -> Result<()> {
        self.transaction(||{
        let mut progress=self.meta("history_download")?.unwrap_or(Value::Null);
        if progress["id"]!=id||progress["revision"]!=revision{progress=json!({"id":id,"revision":revision,"offset":"0","sha256":part["sha256"]});}
        if progress["offset"]!=part["offset"]{return Err(fault("HISTORY_FRAGMENT_INVALID"))}
        if progress["sha256"]!=part["sha256"]{self.c.execute("DELETE FROM local_diff_parts WHERE order_id=? AND revision=?",params![id,revision]).map_err(sql)?;self.put("history_download",&Value::Null)?;return Ok(())}
        let raw=STANDARD.decode(part["data_base64"].as_str().ok_or_else(||fault("HISTORY_FRAGMENT_INVALID"))?).map_err(|_|fault("HISTORY_FRAGMENT_INVALID"))?;
        let offset=number(&part["offset"])?;let end=offset+raw.len() as i64;
        if raw.len()>65536||part["next_offset"].is_string()&&number(&part["next_offset"])?!=end||part["next_offset"].is_null()&&number(&part["total_bytes"])?!=end{return Err(fault("HISTORY_FRAGMENT_INVALID"))}
        self.c.execute("INSERT INTO local_diff_parts VALUES(?,?,?,?) ON CONFLICT(order_id,revision,offset) DO UPDATE SET body=excluded.body",params![id,revision,offset,self.encode(&part["data_base64"])?]).map_err(sql)?;
        if part["next_offset"].is_null(){
            let parts={let mut q=self.c.prepare("SELECT body FROM local_diff_parts WHERE order_id=? AND revision=? ORDER BY offset").map_err(sql)?;let rows=q.query_map(params![id,revision],|r|r.get::<_,Vec<u8>>(0)).map_err(sql)?.collect::<std::result::Result<Vec<_>,_>>().map_err(sql)?;rows};
            let mut full=Vec::new();for raw in parts{let text=self.decode(&raw)?;full.extend(STANDARD.decode(text.as_str().ok_or_else(||fault("HISTORY_FRAGMENT_INVALID"))?).map_err(|_|fault("HISTORY_FRAGMENT_INVALID"))?);}
            if full.len() as i64!=end||quote_ledger::store::hash(&full)!=part["sha256"].as_str().unwrap_or(""){return Err(fault("HISTORY_FRAGMENT_INVALID"))}
            let mut diff:Value=serde_json::from_slice(&full).map_err(json_error)?;
            if diff["revision"]!=revision{return Err(fault("HISTORY_FRAGMENT_INVALID"))}
            public(&mut diff,&self.context()?);self.put(&format!("diff:{id}:{revision}"),&diff)?;
            self.c.execute("DELETE FROM local_diff_parts WHERE order_id=? AND revision=?",params![id,revision]).map_err(sql)?;
            self.c.execute("DELETE FROM local_diff_queue WHERE order_id=? AND revision=?",params![id,revision]).map_err(sql)?;
            self.put("history_download",&Value::Null)?;
        }else{progress["offset"]=part["next_offset"].clone();self.put("history_download",&progress)?;}
        Ok(())
    })
    }
}
