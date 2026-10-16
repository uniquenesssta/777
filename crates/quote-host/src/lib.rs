//! Windows Rust HTTPS host, preserving 777-service-v1 and ledger-v1.
pub mod analytics;
pub mod auth;
pub mod backup;
pub mod devices;
pub mod files;
pub mod host;
pub mod operator;
pub mod outputs;
pub mod protocol;
pub mod query;
pub mod service;
use serde_json::Value;
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
impl From<quote_ledger::Error> for Error {
    fn from(e: quote_ledger::Error) -> Self {
        let (status, code) = match e.code.as_str() {
            "FORBIDDEN" => (403, "FORBIDDEN"),
            "CONFLICT" => (409, "REVISION_OR_PRICE_CONFLICT"),
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
    fn from(_: std::io::Error) -> Self {
        Self::new(503, "HOST_IO_UNAVAILABLE")
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
pub fn casefold(s: &str) -> String {
    use std::{collections::BTreeMap, sync::OnceLock};
    static DATA: OnceLock<BTreeMap<String, String>> = OnceLock::new();
    let data = DATA.get_or_init(|| {
        serde_json::from_str(include_str!("casefold-v15.json")).expect("frozen Unicode15 table")
    });
    s.chars()
        .map(|c| {
            data.get(&c.to_string())
                .cloned()
                .unwrap_or_else(|| c.to_string())
        })
        .collect()
}
pub mod image;

pub mod transport;
