//! Conservative three-way merge. Financially coupled discounts never commute.
use crate::{Error, Result};
use quote_ledger::application::Order;
pub(super) fn conflict(code: &str) -> Error {
    Error::new(409, code)
}
pub(super) fn merge(base: &Order, current: &Order, candidate: &Order, kind: &str) -> Result<Order> {
    if base.owner_id != current.owner_id
        || base.order_id != current.order_id
        || candidate.owner_id != base.owner_id
    {
        return Err(conflict("ORDER_IDENTITY_CONFLICT"));
    }
    if base.revision == current.revision {
        return Ok(candidate.clone());
    }
    if base.state != current.state || kind == "set_state" {
        return Err(conflict("ORDER_STATE_CONFLICT"));
    }
    let mut next = current.clone();
    if kind == "append_note" {
        return Ok(next);
    }
    for key in ["customer", "order_ref", "wechat"] {
        if base.details[key] != candidate.details[key] {
            if current.details[key] != base.details[key]
                && current.details[key] != candidate.details[key]
            {
                return Err(conflict("DETAIL_FIELD_CONFLICT"));
            }
            next.details[key] = candidate.details[key].clone();
        }
    }
    let local = base.lines != candidate.lines;
    let remote = base.lines != current.lines;
    if local
        && remote
        && [base, current, candidate]
            .iter()
            .any(|o| o.lines.iter().any(|l| l.raw["line_kind"] == "discount"))
    {
        return Err(conflict("FINANCIAL_GROUP_CONFLICT"));
    }
    for old in &base.lines {
        let wanted = candidate.lines.iter().find(|l| l.line_id == old.line_id);
        let actual = current.lines.iter().find(|l| l.line_id == old.line_id);
        if wanted == Some(old) {
            continue;
        }
        if actual != Some(old) && actual != wanted {
            return Err(conflict("LINE_FIELD_CONFLICT"));
        }
        let pos = next.lines.iter().position(|l| l.line_id == old.line_id);
        match (pos, wanted) {
            (Some(n), Some(line)) => next.lines[n] = line.clone(),
            (Some(n), None) => {
                next.lines.remove(n);
            }
            (None, Some(_)) => return Err(conflict("LINE_REMOVAL_CONFLICT")),
            _ => (),
        }
    }
    for line in &candidate.lines {
        if base.lines.iter().any(|l| l.line_id == line.line_id) {
            continue;
        }
        if current.lines.iter().any(|l| l.line_id == line.line_id) {
            return Err(conflict("LINE_ID_CONFLICT"));
        }
        next.lines.push(line.clone());
    }
    Ok(next)
}
