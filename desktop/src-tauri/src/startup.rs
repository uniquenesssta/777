//! Native-only deployment material. None of the secrets cross IPC.
use crate::{Connection, DesktopError, Result};
use serde::{Deserialize, Serialize};
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Bootstrap {
    pub schema: String,
    pub delivery: String,
    pub connection: Connection,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ticket: Option<String>,
}
impl Bootstrap {
    pub fn validate(&self, kind: &str) -> Result<()> {
        if self.schema != "777-desktop-bootstrap-v1" || self.delivery != kind {
            return Err(DesktopError::new(403, "DELIVERY_ROLE_MISMATCH"));
        }
        crate::tls::build(&self.connection)?;
        #[cfg(quote777_packaged)]
        {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct PublicConnection {
                schema: String,
                connection: Connection,
            }
            let expected: PublicConnection = serde_json::from_str(include_str!(concat!(
                env!("OUT_DIR"),
                "/package-connection.json"
            )))
            .map_err(|_| DesktopError::new(503, "PACKAGE_CONNECTION_INVALID"))?;
            if expected.schema != "777-public-connection-v1"
                || expected.connection.url.trim_end_matches('/')
                    != self.connection.url.trim_end_matches('/')
                || expected.connection.certificate_sha256 != self.connection.certificate_sha256
                || expected.connection.certificate_pem.trim()
                    != self.connection.certificate_pem.trim()
            {
                return Err(DesktopError::new(403, "PACKAGE_CONNECTION_MISMATCH"));
            }
        }
        if kind != "development"
            && (self.username.is_some()
                || self.password.is_some()
                || self.ticket.as_ref().is_none_or(|s| s.len() != 43))
        {
            return Err(DesktopError::new(422, "DEPLOYMENT_NOT_CONFIGURED"));
        }
        if kind == "development"
            && (self.username.is_none()
                || self.password.is_none()
                || !self.connection.url.starts_with("https://127.0.0.1:"))
        {
            return Err(DesktopError::new(422, "INVALID_DEVELOPMENT_CONFIG"));
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Credential {
    pub config: Bootstrap,
    pub device_id: String,
    pub secret: String,
    pub profile: String,
}
pub fn delivery() -> &'static str {
    if cfg!(feature = "manager") {
        "manager"
    } else if cfg!(feature = "sales") {
        "sales"
    } else {
        "development"
    }
}
pub fn formal() -> bool {
    delivery() != "development"
}
/// Launcher tools have their own loopback authorization, independent of a business login.
pub fn developer_tools() -> bool {
    #[cfg(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    ))]
    {
        crate::developer::available()
    }
    #[cfg(not(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    )))]
    {
        false
    }
}
/// Keep native identities at their existing location when installer IDs become role-specific.
pub fn formal_profile_root(local_app_data: &std::path::Path) -> Option<std::path::PathBuf> {
    formal().then(|| {
        local_app_data
            .join("cn.uniqueness.quote777")
            .join(delivery())
    })
}
#[cfg(quote777_packaged)]
pub fn package_info() -> serde_json::Value {
    let mut info: serde_json::Value = serde_json::from_str(include_str!(concat!(
        env!("OUT_DIR"),
        "/package-metadata.json"
    )))
    .expect("validated package metadata");
    assert_eq!(info["delivery"], delivery(), "PACKAGE_DELIVERY_MISMATCH");
    info["verification"] = serde_json::json!(cfg!(feature = "verification"));
    info["release"] = serde_json::json!(!cfg!(debug_assertions));
    info
}

#[cfg(test)]
mod package_tests {
    #[test]
    fn identity_path_does_not_depend_on_installer_identifier_or_version() {
        let base = std::path::Path::new("user-local-data");
        let root = super::formal_profile_root(base);
        if super::formal() {
            assert_eq!(
                root,
                Some(base.join("cn.uniqueness.quote777").join(super::delivery()))
            );
        } else {
            assert!(root.is_none());
        }
    }

    #[cfg(quote777_packaged)]
    #[test]
    fn native_bootstrap_rejects_an_operator_file_for_another_service() {
        let public: serde_json::Value = serde_json::from_str(include_str!(concat!(
            env!("OUT_DIR"),
            "/package-connection.json"
        )))
        .unwrap();
        let mut bootstrap = super::Bootstrap {
            schema: "777-desktop-bootstrap-v1".into(),
            delivery: super::delivery().into(),
            connection: serde_json::from_value(public["connection"].clone()).unwrap(),
            username: None,
            password: None,
            ticket: Some("a".repeat(43)),
        };
        bootstrap.validate(super::delivery()).unwrap();
        bootstrap.connection.url = "https://localhost:18478".into();
        assert_eq!(
            bootstrap.validate(super::delivery()).unwrap_err().code,
            "PACKAGE_CONNECTION_MISMATCH"
        );
    }
}
