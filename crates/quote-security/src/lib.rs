//! Shared exact certificate identity and Windows account-bound secret protection.
pub mod automatic;
pub mod local_package;
pub mod protect;
pub mod retry;
pub mod tls;
use serde::{Deserialize, Serialize};
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Connection {
    pub url: String,
    pub certificate_pem: String,
    pub certificate_sha256: String,
}
#[derive(Debug)]
pub struct Error {
    pub status: u16,
    pub code: String,
}
impl Error {
    pub fn new(status: u16, code: &str) -> Self {
        Self {
            status,
            code: code.into(),
        }
    }
}
pub type Result<T> = std::result::Result<T, Error>;
