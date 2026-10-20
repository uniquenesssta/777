//! Immutable installed envelope and compiled policy matching.
use super::*;
impl Desktop {
    pub fn load_automatic_package(&mut self, path: &std::path::Path) -> Result<()> {
        use std::io::Read;
        let mut raw = Vec::new();
        std::fs::File::open(path)
            .map_err(|_| DesktopError::new(503, "AUTOMATIC_PACKAGE_UNAVAILABLE"))?
            .take(131073)
            .read_to_end(&mut raw)
            .map_err(|_| invalid())?;
        if raw.len() > 131072 {
            return Err(invalid());
        }
        let p: Package = serde_json::from_slice(&raw).map_err(|_| invalid())?;
        self.accept_automatic_package(p.clone())?;
        self.store.replace("automatic-package.bin", &p)
    }
    pub fn load_background_package(&mut self) -> Result<()> {
        let p: Package = self
            .store
            .read("automatic-package.bin")?
            .ok_or_else(invalid)?;
        self.accept_automatic_package(p)
    }
    fn accept_automatic_package(&mut self, p: Package) -> Result<()> {
        let connection = p
            .validate(crate::startup::delivery())
            .map_err(|e| DesktopError::new(e.status, &e.code))?;
        let caps: Vec<String> =
            serde_json::from_value(p.manifest["capabilities"].clone()).map_err(|_| invalid())?;
        permissions::validate(crate::startup::delivery(), &caps)?;
        #[cfg(quote777_packaged)]
        {
            let meta = crate::startup::package_info();
            let mut expected: Vec<String> =
                serde_json::from_value(meta["permissions"].clone()).map_err(|_| invalid())?;
            expected.sort();
            if meta["package_id"] != p.manifest["package_id"]
                || meta["version"] != p.manifest["release_version"]
                || expected != caps
            {
                return Err(invalid());
            }
            let public: Value = serde_json::from_str(include_str!(concat!(
                env!("OUT_DIR"),
                "/package-connection.json"
            )))
            .map_err(|_| invalid())?;
            if public["connection"]["url"] != connection.url
                || public["connection"]["certificate_sha256"] != connection.certificate_sha256
            {
                return Err(invalid());
            }
        }
        let _ = connection;
        self.automatic_package = Some(p);
        Ok(())
    }
}
