//! Order-level agreed price, applied once after all item discounts.
use crate::models::Fault;

pub fn cents(raw: &str) -> Result<Option<i64>, Fault> {
    let s = raw.trim();
    if s.is_empty() {
        return Ok(None);
    }
    let (whole, fraction) = s.split_once('.').unwrap_or((s, ""));
    if s.len() > 32
        || whole.is_empty()
        || !whole.bytes().all(|c| c.is_ascii_digit())
        || fraction.len() > 2
        || !fraction.bytes().all(|c| c.is_ascii_digit())
    {
        return Err(Fault::new("FINAL_PRICE_INVALID", "final_price"));
    }
    let major = whole
        .parse::<i64>()
        .map_err(|_| Fault::new("FINAL_PRICE_INVALID", "final_price"))?;
    let minor = format!("{fraction:0<2}")
        .parse::<i64>()
        .map_err(|_| Fault::new("FINAL_PRICE_INVALID", "final_price"))?;
    major
        .checked_mul(100)
        .and_then(|n| n.checked_add(minor))
        .map(Some)
        .ok_or_else(|| Fault::new("FINAL_PRICE_INVALID", "final_price"))
}
