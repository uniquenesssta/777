//! Export snapshots are read from the ledger; generation and history stay local.
use super::*;
use crate::local_outputs::{self, jobs};
use sha2::{Digest, Sha256};
impl Desktop {
    pub(super) fn export_scope(&self) -> Result<String> {
        let s = self.session()?;
        Ok(format!(
            "{:x}",
            Sha256::digest(format!(
                "{}|{}|{}|{}|{}",
                s.connection.url,
                s.connection.certificate_sha256,
                s.subject,
                s.role,
                permissions::has(&permissions::selected()?, "finance")
            ))
        ))
    }
    pub(super) fn export_job(&self, id: &str) -> Result<Value> {
        let job = jobs::get(&self.store, &self.export_scope()?, id)?;
        if matches!(job["kind"].as_str(), Some("excel_admin" | "excel_period")) {
            self.admin()?;
            permissions::require(&permissions::selected()?, "finance")?;
        }
        Ok(job)
    }
    pub(super) async fn create_local_export(
        &mut self,
        order_id: &str,
        expected: &str,
        kind: &str,
    ) -> Result<Value> {
        local_outputs::root(&self.store)?;
        local_outputs::folder(kind)?;
        let mut order = self
            .request(
                "GET",
                &format!("/v1/orders/{}", identifier(order_id)?),
                None,
            )
            .await?;
        if order["revision"].as_i64() != Some(revision(expected)?) {
            return Err(DesktopError::new(409, "ORDER_REVISION_CHANGED"));
        }
        if kind != "excel_admin" {
            permissions::redact_financial(&mut order);
            if let Some(o) = order.as_object_mut() {
                o.remove("history");
            }
        }
        let payload = json!({"format":"777-output-v1","presentation":"monthly-v1","generated_at":quote_ledger::store::now(),"job_id":new_id()?,"kind":kind,"order":order});
        self.publish_local_export(&payload)
    }
    pub(super) fn publish_local_export(&self, payload: &Value) -> Result<Value> {
        let scope = self.export_scope()?;
        let job = jobs::insert(&self.store, &scope, payload)?;
        local_outputs::execute(&self.store, &scope, job["job_id"].as_str().unwrap())
    }
    pub(super) fn local_output_listing(&self, offset: u32) -> Result<Value> {
        let scope = self.export_scope()?;
        let mut page = jobs::list(&self.store, &scope, offset)?;
        if let Some(rows) = page["jobs"].as_array_mut() {
            for job in rows {
                if job["state"] == "queued" {
                    *job = local_outputs::execute(
                        &self.store,
                        &scope,
                        job["job_id"].as_str().unwrap(),
                    )?;
                }
            }
        }
        Ok(page)
    }
}
