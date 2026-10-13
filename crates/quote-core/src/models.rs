use crate::numbers::rounded_ratio;
use num_bigint::BigInt;
use num_traits::Signed;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const RULE_VERSION: &str = "business-v1";
pub const NUMERIC_PROFILE: &str = "numeric-v1";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fault {
    pub reason: String,
    pub field: String,
}
impl Fault {
    pub fn new(reason: &str, field: &str) -> Self {
        Self {
            reason: reason.into(),
            field: field.into(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Issue {
    pub code: String,
    pub reason: String,
    pub field: String,
    pub line_index: Option<usize>,
}
impl Issue {
    pub fn validation(f: Fault, index: Option<usize>) -> Self {
        Self {
            code: "VALIDATION".into(),
            reason: f.reason,
            field: f.field,
            line_index: index,
        }
    }
    pub fn problem(code: &str, reason: &str, field: &str) -> Self {
        Self {
            code: code.into(),
            reason: reason.into(),
            field: field.into(),
            line_index: None,
        }
    }
}
fn empty() -> Value {
    json!("")
}
fn default_rule() -> Value {
    json!(RULE_VERSION)
}
fn default_profile() -> Value {
    json!(NUMERIC_PROFILE)
}
fn discount_name() -> Value {
    json!("折扣")
}
fn no() -> Value {
    json!(false)
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Line {
    Normal {
        product_id: Value,
        q: Value,
        #[serde(default = "empty")]
        h: Value,
        #[serde(default = "empty")]
        w: Value,
        #[serde(default = "empty")]
        name: Value,
    },
    Discount {
        percent: Value,
        #[serde(default = "discount_name")]
        name: Value,
    },
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PriceItem {
    pub product_id: Value,
    pub sale: Value,
    pub cost: Value,
    #[serde(default = "empty")]
    pub k: Value,
    #[serde(default = "no")]
    pub single: Value,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Prices {
    pub price_version_id: Value,
    pub items: Vec<PriceItem>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Quote {
    pub price_version_id: Value,
    pub lines: Vec<Line>,
    #[serde(default = "default_rule")]
    pub rule_version: Value,
    #[serde(default = "default_profile")]
    pub numeric_profile: Value,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Amounts {
    income: i64,
    cost: i64,
    discount: bool,
}
impl Amounts {
    pub fn new(income: i64, cost: i64, discount: bool) -> Result<Self, Fault> {
        if income == i64::MIN
            || cost == i64::MIN
            || income.checked_sub(cost).is_none_or(|n| n == i64::MIN)
        {
            return Err(Fault::new("MONEY_CAPACITY", "amounts"));
        }
        Ok(Self {
            income,
            cost,
            discount,
        })
    }
    pub fn income(&self) -> i64 {
        self.income
    }
    pub fn cost(&self) -> i64 {
        self.cost
    }
    pub fn profit(&self) -> i64 {
        self.income - self.cost
    }
    pub fn display(&self) -> Value {
        let margin = if self.income == 0 || self.discount {
            None
        } else {
            let n = rounded_ratio(BigInt::from(self.profit()) * 100u8, self.income.into(), 1)
                .expect("nonzero denominator");
            Some(format!(
                "{}{}.{}%",
                if n.is_negative() { "-" } else { "" },
                n.abs() / 10u8,
                n.abs() % 10u8
            ))
        };
        json!({"income":money_text(self.income),"cost":money_text(self.cost),"profit":money_text(self.profit()),"margin":margin})
    }
    pub fn cents(&self) -> Value {
        json!({"income_cents":self.income.to_string(),"cost_cents":self.cost.to_string(),"profit_cents":self.profit().to_string()})
    }
}
fn money_text(n: i64) -> String {
    let n = BigInt::from(n);
    format!(
        "{}{}.{:0>2}",
        if n.is_negative() { "-" } else { "" },
        n.abs() / 100u8,
        n.abs() % 100u8
    )
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CalculatedLine {
    pub sequence: usize,
    pub raw: Line,
    pub price: Option<PriceItem>,
    pub normalized: Vec<(String, String)>,
    pub amounts: Amounts,
    pub subtotal_before: i64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuoteResult {
    pub status: String,
    pub rule_version: Value,
    pub numeric_profile: Value,
    pub price_version_id: Value,
    pub lines: Option<Vec<CalculatedLine>>,
    pub totals: Option<Amounts>,
    pub issues: Vec<Issue>,
    pub warnings: Vec<Issue>,
}
impl QuoteResult {
    pub fn invalid(q: Option<&Quote>, issues: Vec<Issue>) -> Self {
        Self {
            status: "VALIDATION".into(),
            rule_version: q.map_or_else(default_rule, |q| q.rule_version.clone()),
            numeric_profile: q.map_or_else(default_profile, |q| q.numeric_profile.clone()),
            price_version_id: q.map_or_else(empty, |q| q.price_version_id.clone()),
            lines: None,
            totals: None,
            issues,
            warnings: vec![],
        }
    }
    pub fn wire(&self) -> Value {
        let lines=self.lines.as_ref().map(|ls|ls.iter().map(|l|json!({"sequence":l.sequence,"raw":l.raw,"price":l.price,"normalized":l.normalized,"amounts":l.amounts.cents(),"display":l.amounts.display(),"subtotal_before_cents":l.subtotal_before.to_string()})).collect::<Vec<_>>());
        json!({"status":self.status,"rule_version":self.rule_version,"numeric_profile":self.numeric_profile,"price_version_id":self.price_version_id,"lines":lines,"totals":self.totals.as_ref().map(Amounts::cents),"display":{"status":self.status,"lines":self.lines.as_ref().map(|ls|ls.iter().map(|l|l.amounts.display()).collect::<Vec<_>>()),"totals":self.totals.as_ref().map(Amounts::display)},"issues":self.issues,"warnings":self.warnings})
    }
}
// A mutable container cannot become a snapshot field, including ignored dimensions.
pub fn scalar(v: &Value, field: &str) -> Result<(), Fault> {
    if v.is_array() || v.is_object() {
        Err(Fault::new("SNAPSHOT_SCALAR_TYPE", field))
    } else {
        Ok(())
    }
}
pub fn validate_models(q: &Quote, p: &Prices) -> Result<(), Fault> {
    for l in &q.lines {
        match l {
            Line::Normal {
                product_id,
                q,
                h,
                w,
                name,
            } => {
                for (v, f) in [
                    (product_id, "product_id"),
                    (q, "q"),
                    (h, "h"),
                    (w, "w"),
                    (name, "name"),
                ] {
                    scalar(v, f)?
                }
            }
            Line::Discount { percent, name } => {
                scalar(percent, "percent")?;
                scalar(name, "name")?;
            }
        }
    }
    for item in &p.items {
        for (v, f) in [
            (&item.product_id, "product_id"),
            (&item.sale, "sale"),
            (&item.cost, "cost"),
            (&item.k, "k"),
            (&item.single, "single"),
        ] {
            scalar(v, f)?;
        }
    }
    for (v, f) in [
        (&q.price_version_id, "price_version_id"),
        (&q.rule_version, "rule_version"),
        (&q.numeric_profile, "numeric_profile"),
        (&p.price_version_id, "price_version_id"),
    ] {
        scalar(v, f)?;
    }
    Ok(())
}
