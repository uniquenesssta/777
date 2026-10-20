//! Host status mapping around the shared offline business contract.
use crate::{Error, Result};
use serde_json::Value;
pub(super) fn validate(v: &Value) -> Result<()> {
    quote_ledger::intake::payload::validate(v).map_err(|e| Error::new(422, &e.code))
}
