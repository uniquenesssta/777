use super::*;
impl Desktop {
    pub(super) async fn business_directory(&mut self, directory: Option<String>) -> Result<Value> {
        if crate::startup::delivery() != "manager" {
            return Err(DesktopError::new(403, "ADMIN_REQUIRED"));
        }
        self.admin()?;
        let ledger = connections::identity(self.session()?).await?;
        crate::directory_preference::preference(&self.store, &ledger, directory)
    }
}
