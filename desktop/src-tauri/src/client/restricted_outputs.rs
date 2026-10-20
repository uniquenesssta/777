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
}
