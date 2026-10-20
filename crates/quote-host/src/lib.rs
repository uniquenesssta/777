//! Windows Rust HTTPS host, preserving 777-service-v1 and versioned ledgers.
#[cfg(test)]
extern crate self as quote_host;
pub mod analytics;
pub mod auth;
pub mod automatic;
#[cfg(test)]
#[allow(dead_code)]
#[path = "../tests/automatic_support/mod.rs"]
mod automatic_fixture;
pub mod backup;
pub mod backup_settings;
pub mod cluster;
mod customers;
pub mod daily_backup;
pub mod devices;
pub mod files;
pub mod host;
pub mod offline;
pub mod operator;
mod order_changes;
pub mod outputs;
mod price_catalog;
pub mod protocol;
pub mod query;
pub mod recovery;
mod report_exports;
pub mod service;
use serde_json::Value;
#[derive(Debug)]
pub struct Error {
    pub status: u16,
    pub retry_after: Option<u64>,
    pub code: String,
}
impl Error {
    pub fn new(status: u16, code: &str) -> Self {
        Self {
            status,
            code: code.into(),
            retry_after: None,
        }
    }
}
impl From<quote_ledger::Error> for Error {
    fn from(e: quote_ledger::Error) -> Self {
        let (status, code) = match e.code.as_str() {
            "FILESYSTEM_PATH_REQUIRED" => (422, "FILESYSTEM_PATH_REQUIRED"),
            "PATH_UNAVAILABLE" => (503, "PATH_UNAVAILABLE"),
            "PATH_PERMISSION_DENIED" => (403, "PATH_PERMISSION_DENIED"),
            "LINK_OR_TYPE_DISALLOWED" => (422, "PATH_TYPE_CONFLICT"),
            "FORBIDDEN" => (403, "FORBIDDEN"),
            "CONFLICT" => (409, "REVISION_OR_PRICE_CONFLICT"),
            "CUSTOMER_SELECTION_REQUIRED" => (409, "CUSTOMER_SELECTION_REQUIRED"),
            "CUSTOMER_IDENTITY_CONFLICT" => (409, "CUSTOMER_IDENTITY_CONFLICT"),
            "CUSTOMER_ORDER_NUMBER_EXISTS" => (409, "CUSTOMER_ORDER_NUMBER_EXISTS"),
            "BUSY" => (503, "STORE_BUSY_OR_UNAVAILABLE"),
            "PRICES_NOT_PUBLISHED" => (409, "PRICES_NOT_PUBLISHED"),
            "INVALID_DATABASE" => (503, "LEDGER_UNAVAILABLE"),
            _ => (422, "INVALID_BUSINESS_INPUT"),
        };
        Self::new(status, code)
    }
}
impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        quote_ledger::Error::from(e).into()
    }
}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        quote_diagnostics::io_error("host.io", None, &e);
        match e.kind() {
            std::io::ErrorKind::PermissionDenied => Self::new(403, "PATH_PERMISSION_DENIED"),
            std::io::ErrorKind::NotFound => Self::new(503, "PATH_UNAVAILABLE"),
            std::io::ErrorKind::AlreadyExists => Self::new(409, "PATH_ALREADY_EXISTS"),
            _ => Self::new(503, "HOST_IO_UNAVAILABLE"),
        }
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::new(422, "INVALID_JSON")
    }
}
impl From<quote_excel::Error> for Error {
    fn from(e: quote_excel::Error) -> Self {
        Self::new(422, &e.code)
    }
}
pub type Result<T> = std::result::Result<T, Error>;
pub fn fail<T>(status: u16, code: &str) -> Result<T> {
    Err(Error::new(status, code))
}
pub fn number(v: &Value) -> Result<i64> {
    v.as_i64()
        .ok_or_else(|| Error::new(422, "INVALID_BUSINESS_INPUT"))
}
pub use quote_core::search::casefold;

pub mod image;
pub mod intake;

pub mod transport;
