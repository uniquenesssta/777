use crate::{
    models::*,
    numbers::{parse_number, parse_percent, Decimal},
};
use serde_json::json;
use std::collections::HashMap;

pub fn calculate(q: &Quote, p: &Prices) -> QuoteResult {
    let mut index = None;
    match calculate_checked(q, p, &mut index) {
        Ok(r) => r,
        Err(f) => QuoteResult::invalid(Some(q), vec![Issue::validation(f, index)]),
    }
}
fn calculate_checked(
    q: &Quote,
    p: &Prices,
    index: &mut Option<usize>,
) -> Result<QuoteResult, Fault> {
    validate_models(q, p)?;
    if q.rule_version != json!(RULE_VERSION) || q.numeric_profile != json!(NUMERIC_PROFILE) {
        return Err(Fault::new("RULE_VERSION_UNSUPPORTED", "rule_version"));
    }
    if q.price_version_id.as_str().is_none_or(|s| s.is_empty())
        || q.price_version_id != p.price_version_id
    {
        return Err(Fault::new("PRICE_VERSION_MISMATCH", "price_version_id"));
    }
    if q.lines.is_empty() || q.lines.len() > 10000 {
        return Err(Fault::new("LINE_CAPACITY", "lines"));
    }
    let mut catalog = HashMap::new();
    for item in &p.items {
        let id = item
            .product_id
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| Fault::new("PRICE_ID_INVALID_OR_DUPLICATE", "prices"))?;
        if catalog.insert(id, item).is_some() {
            return Err(Fault::new("PRICE_ID_INVALID_OR_DUPLICATE", "prices"));
        }
    }
    let (mut income, mut cost) = (0i64, 0i64);
    let mut lines = vec![];
    let mut warnings = vec![];
    for (i, raw) in q.lines.iter().enumerate() {
        *index = Some(i + 1);
        let before = income;
        let (amounts, price, normalized) = match raw {
            Line::Discount { percent, .. } => {
                let percent = parse_percent(percent)?;
                let factor = percent
                    .mul(&Decimal::new(1.into(), 2))
                    .sub(&Decimal::integer(1));
                let sale = Decimal::cents(income).mul(&factor).settle()?;
                if income == 0 {
                    warnings.push(Issue {
                        code: "WARNING".into(),
                        reason: "DISCOUNT_ZERO_SUBTOTAL".into(),
                        field: "percent".into(),
                        line_index: *index,
                    });
                }
                (
                    Amounts::new(sale, 0, true)?,
                    None,
                    vec![("percent".into(), percent.text())],
                )
            }
            Line::Normal {
                product_id,
                q,
                h,
                w,
                ..
            } => {
                let price = product_id
                    .as_str()
                    .and_then(|id| catalog.get(id))
                    .ok_or_else(|| Fault::new("PRODUCT_NOT_FOUND", "product_id"))?;
                let single = price
                    .single
                    .as_bool()
                    .ok_or_else(|| Fault::new("SINGLE_NOT_BOOLEAN", "single"))?;
                let q = parse_number(q, "q", false)?;
                let mut normalized = vec![("q".into(), q.text())];
                let mut base = q;
                if !single {
                    let h = parse_number(h, "h", false)?;
                    let w = parse_number(w, "w", false)?;
                    base = h.mul(&w).checked()?.mul(&base).checked()?;
                    normalized.extend([("h".into(), h.text()), ("w".into(), w.text())]);
                }
                let sale = parse_number(&price.sale, "sale", false)?;
                let expense = parse_number(&price.cost, "cost", false)?;
                let k = parse_number(&price.k, "k", true)?;
                let amount = Amounts::new(
                    base.mul(&sale).checked()?.mul(&k).checked()?.settle()?,
                    base.mul(&expense).checked()?.settle()?,
                    false,
                )?;
                normalized.extend([
                    ("sale".into(), sale.text()),
                    ("cost".into(), expense.text()),
                    ("k".into(), k.text()),
                ]);
                (amount, Some((*price).clone()), normalized)
            }
        };
        income = income
            .checked_add(amounts.income())
            .ok_or_else(|| Fault::new("MONEY_CAPACITY", "amounts"))?;
        cost = cost
            .checked_add(amounts.cost())
            .ok_or_else(|| Fault::new("MONEY_CAPACITY", "amounts"))?;
        Amounts::new(income, cost, false)?;
        lines.push(CalculatedLine {
            sequence: i + 1,
            raw: raw.clone(),
            price,
            normalized,
            amounts,
            subtotal_before: before,
        });
    }
    Ok(QuoteResult {
        status: "ok".into(),
        rule_version: q.rule_version.clone(),
        numeric_profile: q.numeric_profile.clone(),
        price_version_id: q.price_version_id.clone(),
        lines: Some(lines),
        totals: Some(Amounts::new(income, cost, false)?),
        issues: vec![],
        warnings,
    })
}
