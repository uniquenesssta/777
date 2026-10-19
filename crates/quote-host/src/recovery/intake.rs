//! Schema-3 logical table coverage without restoring credentials or enabling intake.
use super::*;
pub(super) fn tables(format: &str) -> Vec<&'static str> {
    if format == LEGACY_FORMAT {
        return LEGACY_LEDGER.to_vec();
    }
    let mut names = LEDGER.to_vec();
    if format == FORMAT_V3 {
        names.extend(quote_ledger::intake::TABLES);
    }
    names
}
pub(super) fn prepare(c: &mut Connection, data: &Data) -> Result<()> {
    if data.format == FORMAT_V3 {
        quote_ledger::intake::upgrade(c)?;
    }
    Ok(())
}
