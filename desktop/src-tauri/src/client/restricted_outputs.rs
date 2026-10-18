use super::*;
impl Desktop {
    pub(super) async fn authorize_output(&mut self, id: &str) -> Result<()> {
        let policy = permissions::selected()?;
        permissions::require(&policy, "exports")?;
        if !permissions::has(&policy, "finance") {
            let job = self
                .request("GET", &format!("/v1/outputs/{}", identifier(id)?), None)
                .await?;
            if !["excel_quote", "quote_png"].contains(&job["kind"].as_str().unwrap_or("")) {
                return Err(DesktopError::new(403, "PACKAGE_PERMISSION_DENIED"));
            }
        }
        Ok(())
    }
    pub(super) async fn visible_outputs(&mut self, offset: u32) -> Result<Value> {
        if permissions::has(&permissions::selected()?, "finance") {
            return self
                .request("GET", &format!("/v1/outputs?offset={offset}"), None)
                .await;
        }
        // Old Hosts only accept offset. Filter in native code without leaking the
        // financial rows or their total. Stop after one visible page plus lookahead.
        let mut visible = Vec::new();
        let mut seen = 0u32;
        for source_offset in (0..=100_000u32).step_by(100) {
            let page = self
                .request("GET", &format!("/v1/outputs?offset={source_offset}"), None)
                .await?;
            let jobs = page["jobs"]
                .as_array()
                .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?;
            for job in jobs {
                if ["excel_quote", "quote_png"].contains(&job["kind"].as_str().unwrap_or("")) {
                    if seen >= offset {
                        visible.push(job.clone());
                    }
                    seen += 1;
                    if visible.len() > 100 {
                        visible.truncate(100);
                        return Ok(
                            json!({"jobs":visible,"offset":offset,"limit":100,"total":seen,"has_more":true,"format":"777-output-v1"}),
                        );
                    }
                }
            }
            if jobs.len() < 100 || source_offset + 100 >= page["total"].as_u64().unwrap_or(0) as u32
            {
                return Ok(
                    json!({"jobs":visible,"offset":offset,"limit":100,"total":seen,"has_more":false,"format":"777-output-v1"}),
                );
            }
        }
        Err(DesktopError::new(409, "OUTPUT_LIST_LIMIT"))
    }
}
