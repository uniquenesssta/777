use super::*;
impl Desktop {
    /// Called by the native lifetime worker, never by a React interval.
    pub async fn sync_tick(&mut self) -> Result<bool> {
        if self.automatic_package.is_none() {
            return Ok(false);
        }
        self.reconnect_probe().await?;
        self.automatic_retry.ready()?;
        let Some(_transport) = self.local.sync_guard()? else {
            return Ok(false);
        };
        let result = self.sync_on().await;
        if result
            .as_ref()
            .is_err_and(|e| [401, 403].contains(&e.status))
        {
            self.local.put("denied", &json!(true))?;
            self.auto_expires = 0;
        }
        self.automatic_retry
            .record(&result.as_ref().map(|v| json!(v)).map_err(Clone::clone));
        result
    }
    async fn sync_on(&mut self) -> Result<bool> {
        if self.session.as_ref().is_none_or(|s| s.token.is_empty())
            || self.auto_expires <= clock() + 30
        {
            self.bootstrap_automatic().await?;
        }
        if self.has_pending()? {
            self.execute_inner(Action::Recover { retry: true }).await?;
        }
        if !self.local.active()? {
            let s = self.session()?.clone();
            let p = self.automatic_package.as_ref().unwrap().clone();
            let device = self
                .store
                .read::<Value>("automatic-device.bin")?
                .ok_or_else(context_error)?;
            self.prepare_local(&s, device["id"].as_str().ok_or_else(context_error)?, &p)
                .await?;
            if !self.local.active()? {
                return Ok(false);
            }
        }
        if self
            .local
            .meta("ready_checked")?
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            + 60
            < crate::offline::now()
        {
            let s = self.session()?.clone();
            let p = self.automatic_package.as_ref().unwrap().clone();
            let device = self.local.meta("context")?.ok_or_else(context_error)?["binding"]
                ["device"]
                .as_str()
                .ok_or_else(context_error)?
                .to_owned();
            self.prepare_local(&s, &device, &p).await?;
            self.local
                .put("ready_checked", &json!(crate::offline::now()))?;
        }
        let ops = self.local.upload()?;
        let mut changed = false;
        if !ops.is_empty() {
            let response = self
                .request(
                    "POST",
                    "/v1/offline/operations",
                    Some(&json!({"protocol":FORMAT,"batch_id":new_id()?,"operations":ops})),
                )
                .await?;
            self.local.receipts(&response["receipts"])?;
            changed = true;
        }
        let ids = self.local.receipt_ids()?;
        if !ids.is_empty() {
            let response = self
                .request(
                    "POST",
                    "/v1/offline/receipts",
                    Some(&json!({"protocol":FORMAT,"operation_ids":ids})),
                )
                .await?;
            self.local.receipts(&response["receipts"])?;
        }
        if permissions::has(&permissions::selected()?, "orders") {
            changed |= self.download_tick().await?;
        }
        Ok(changed)
    }
}
