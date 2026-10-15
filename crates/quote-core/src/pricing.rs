//! Explicit final-price modes; absent mode preserves the original sale-times-K rule.
use crate::{
    models::{Fault, PriceItem, PricingMode},
    numbers::{parse_number, Decimal},
};
pub fn unit_sale(price: &PriceItem) -> Result<Decimal, Fault> {
    let cost = parse_number(&price.cost, "cost", false)?;
    let k = parse_number(&price.k, "k", true)?;
    match price.pricing_mode {
        Some(PricingMode::CostPlus) => cost.mul(&k).checked(),
        Some(PricingMode::Manual) => parse_number(&price.sale, "sale", false),
        None => parse_number(&price.sale, "sale", false)?.mul(&k).checked(),
    }
}
