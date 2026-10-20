use super::*;
impl Desktop {
    pub(super) async fn download_tick(&mut self) -> Result<bool> {
        if crate::offline::now() % 3 == 0 && self.history_tick().await? {
            return Ok(true);
        }
        let mut pending = self.local.meta("feed_pending")?.unwrap_or(Value::Null);
        if pending.is_null() {
            let cursor = self.local.meta("feed_cursor")?.unwrap_or(Value::Null);
            pending = match self
                .request(
                    "POST",
                    "/v1/offline/changes",
                    Some(&json!({"protocol":FORMAT,"cursor":cursor})),
                )
                .await
            {
                Ok(v) => v,
                Err(e) if e.code == "OFFLINE_CURSOR_REBUILD_REQUIRED" => {
                    self.local.put("feed_cursor", &Value::Null)?;
                    return Ok(false);
                }
                Err(e) => return Err(e),
            };
            self.local.put("feed_pending", &pending)?;
        }
        let items = pending["changes"]
            .as_array_mut()
            .ok_or_else(context_error)?;
        if items.is_empty() {
            self.local.put("feed_cursor", &pending["cursor"])?;
            self.local.put("feed_pending", &Value::Null)?;
            return self.history_tick().await;
        }
        let item = items[0].clone();
        let id = item["order_id"].as_str().ok_or_else(context_error)?;
        let mut progress = self.local.meta("download")?.unwrap_or(Value::Null);
        if progress["order_id"] != id || progress["revision"] != item["order_revision"] {
            progress = json!({"order_id":id,"revision":item["order_revision"],"section":"lines","offset":"0","view":{"lines":[],"notes":[],"history":[]}});
        }
        let ctx = self.local.context()?;
        let chunk=match self.request("POST","/v1/offline/order-chunk",Some(&json!({"protocol":FORMAT,"epoch":ctx["lease"]["body"]["epoch"],"order_id":id,"revision":progress["revision"],"section":progress["section"],"offset":progress["offset"]}))).await{
            Ok(v)=>v,Err(e)if e.status==409=>{self.local.put("feed_pending",&Value::Null)?;self.local.put("download",&Value::Null)?;return Ok(false)},Err(e)=>return Err(e)
        };
        if chunk["order"]["order_id"] != id
            || chunk["order"]["revision"] != progress["revision"]
            || chunk["section"] != progress["section"]
        {
            return Err(context_error());
        }
        let section = progress["section"].as_str().unwrap().to_owned();
        let rows = chunk["items"].as_array().ok_or_else(context_error)?;
        progress["view"][&section]
            .as_array_mut()
            .ok_or_else(context_error)?
            .extend(rows.iter().cloned());
        for (key, value) in chunk["order"].as_object().ok_or_else(context_error)? {
            progress["view"][key] = value.clone();
        }
        if chunk["next_offset"].is_null() {
            if section == "lines" {
                progress["section"] = json!("notes");
                progress["offset"] = json!("0");
            } else if section == "notes" {
                progress["section"] = json!("history");
                progress["offset"] = json!("0");
            } else {
                let view = progress["view"].clone();
                self.local.receive_order(view)?;
                pending["changes"].as_array_mut().unwrap().remove(0);
                self.local.put("feed_pending", &pending)?;
                self.local.put("download", &Value::Null)?;
                return Ok(true);
            }
        } else {
            progress["offset"] = chunk["next_offset"].clone();
        }
        self.local.put("download", &progress)?;
        Ok(true)
    }
}
