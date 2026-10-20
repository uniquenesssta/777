use super::*;
impl Desktop {
    pub(super) async fn history_tick(&mut self) -> Result<bool> {
        let Some((id, revision)) = self.local.history_task()? else {
            return Ok(false);
        };
        let progress = self.local.meta("history_download")?.unwrap_or(Value::Null);
        let offset = if progress["id"] == id && progress["revision"] == revision {
            progress["offset"].clone()
        } else {
            json!("0")
        };
        let ctx = self.local.context()?;
        let part=self.request("POST","/v1/offline/diff-chunk",Some(&json!({"protocol":FORMAT,"epoch":ctx["lease"]["body"]["epoch"],"order_id":id,"revision":revision,"offset":offset}))).await?;
        self.local.history_part(&id, &revision, &part)?;
        Ok(true)
    }
}
