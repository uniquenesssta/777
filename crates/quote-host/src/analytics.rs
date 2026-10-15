//! Read-only business-calendar aggregates; all money stays integer cents.
use crate::{fail, Error, Result};
use num_bigint::BigInt;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};
use time::{
    format_description::well_known::Rfc3339, Date, Duration, Month, OffsetDateTime, UtcOffset,
};

#[derive(Default)]
struct Totals {
    count: u64,
    money: [BigInt; 3],
}
impl Totals {
    fn add(&mut self, money: [i64; 3]) {
        self.count += 1;
        for (sum, value) in self.money.iter_mut().zip(money) {
            *sum += value;
        }
    }
    fn value(&self) -> Value {
        let income = &self.money[0];
        let profit = &self.money[2];
        let margin = if income == &BigInt::from(0) {
            None
        } else {
            let negative = profit < &BigInt::from(0);
            let p = if negative { -profit } else { profit.clone() };
            let n: BigInt = (p * 1000 + income / 2) / income;
            Some(format!(
                "{}{}.{}%",
                if negative && n != BigInt::from(0) {
                    "-"
                } else {
                    ""
                },
                &n / 10,
                &n % 10
            ))
        };
        json!({"order_count":self.count,"income_cents":income.to_string(),"cost_cents":self.money[1].to_string(),"profit_cents":profit.to_string(),"margin":margin})
    }
}
fn invalid() -> Error {
    Error::new(422, "INVALID_ANALYTICS_QUERY")
}
fn date(raw: &str) -> Result<Date> {
    if raw.len() != 10
        || !raw.bytes().enumerate().all(|(i, c)| {
            if [4, 7].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_digit()
            }
        })
    {
        return Err(invalid());
    }
    let format = time::format_description::parse("[year]-[month]-[day]").map_err(|_| invalid())?;
    Date::parse(raw, &format).map_err(|_| invalid())
}
fn key(d: Date, period: &str) -> Result<Date> {
    match period {
        "day" => Ok(d),
        "week" => d
            .checked_sub(Duration::days(d.weekday().number_days_from_monday().into()))
            .ok_or_else(invalid),
        "month" => Date::from_calendar_date(d.year(), d.month(), 1).map_err(|_| invalid()),
        "year" => Date::from_calendar_date(d.year(), Month::January, 1).map_err(|_| invalid()),
        _ => Err(invalid()),
    }
}
fn next(d: Date, period: &str) -> Result<Date> {
    match period {
        "day" => d.next_day().ok_or_else(invalid),
        "week" => d.checked_add(Duration::days(7)).ok_or_else(invalid),
        "month" => Date::from_calendar_date(
            if d.month() == Month::December {
                d.year() + 1
            } else {
                d.year()
            },
            d.month().next(),
            1,
        )
        .map_err(|_| invalid()),
        "year" => Date::from_calendar_date(d.year() + 1, Month::January, 1).map_err(|_| invalid()),
        _ => Err(invalid()),
    }
}
pub fn summarize<'a>(
    query: &str,
    rows: impl IntoIterator<Item = (&'a str, [i64; 3])>,
    revision: i64,
) -> Result<Value> {
    let mut parameters = HashMap::new();
    for (k, v) in form_urlencoded::parse(query.as_bytes()) {
        if !["period", "from", "to"].contains(&k.as_ref())
            || parameters.insert(k.into_owned(), v.into_owned()).is_some()
        {
            return Err(invalid());
        }
    }
    let get = |k: &str| parameters.get(k).map(String::as_str).ok_or_else(invalid);
    let period = get("period")?;
    let from = date(get("from")?)?;
    let to = date(get("to")?)?;
    if from > to {
        return Err(invalid());
    }
    let mut buckets = BTreeMap::new();
    let mut d = key(from, period)?;
    let end = key(to, period)?;
    loop {
        if buckets.len() >= 400 {
            return fail(422, "ANALYTICS_RANGE_TOO_LARGE");
        }
        buckets.insert(d, Totals::default());
        if d == end {
            break;
        }
        d = next(d, period)?;
    }
    let offset = UtcOffset::from_hms(8, 0, 0).map_err(|_| invalid())?;
    let legacy = time::format_description::parse("[year]-[month]-[day] [hour]:[minute]:[second]")
        .map_err(|_| invalid())?;
    let mut total = Totals::default();
    let mut unplaced = 0u64;
    for (raw, money) in rows {
        let parsed = OffsetDateTime::parse(raw, &Rfc3339)
            .map(|v| v.to_offset(offset).date())
            .or_else(|_| time::PrimitiveDateTime::parse(raw, &legacy).map(|v| v.date()));
        let Ok(day) = parsed else {
            unplaced += 1;
            continue;
        };
        if day < from || day > to {
            continue;
        }
        if let Some(bucket) = buckets.get_mut(&key(day, period)?) {
            bucket.add(money);
            total.add(money);
        }
    }
    Ok(
        json!({"format":"777-profit-analysis-v1","timezone":"Asia/Shanghai","week_starts_on":"Monday","period":period,"from":from.to_string(),"to":to.to_string(),"ledger_revision":revision.to_string(),"unplaced_date_orders":unplaced,"totals":total.value(),"buckets":buckets.into_iter().map(|(day,t)|json!({"start":day.to_string(),"totals":t.value()})).collect::<Vec<_>>()}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn business_midnight_empty_days_and_exact_large_aggregates() {
        let v = summarize(
            "period=day&from=2026-01-01&to=2026-01-03",
            [
                ("2025-12-31T16:00:00Z", [i64::MAX, 4, i64::MAX - 4]),
                ("2026-01-01T15:59:59Z", [10, 20, -10]),
                ("2026-01-03T16:00:00Z", [99, 0, 99]),
            ],
            7,
        )
        .unwrap();
        assert_eq!(v["totals"]["income_cents"], "9223372036854775817");
        assert_eq!(v["totals"]["order_count"], 2);
        assert_eq!(v["buckets"][1]["totals"]["income_cents"], "0");
        assert_eq!(v["buckets"].as_array().unwrap().len(), 3);
    }
    #[test]
    fn monday_weeks_cross_year_and_negative_margin() {
        let v = summarize(
            "period=week&from=2025-12-29&to=2026-01-11",
            [
                ("2026-01-04T15:59:59Z", [100, 120, -20]),
                ("2026-01-04T16:00:00Z", [200, 0, 200]),
            ],
            1,
        )
        .unwrap();
        assert_eq!(v["buckets"][0]["start"], "2025-12-29");
        assert_eq!(v["buckets"][0]["totals"]["margin"], "-20.0%");
        assert_eq!(v["buckets"][1]["totals"]["income_cents"], "200");
    }
    #[test]
    fn leap_months_years_and_unknown_legacy_dates() {
        let v = summarize(
            "period=month&from=2024-01-01&to=2024-03-01",
            [("2024-02-29 23:59:59", [1, 0, 1]), ("unknown", [9, 0, 9])],
            1,
        )
        .unwrap();
        assert_eq!(v["unplaced_date_orders"], 1);
        assert_eq!(v["buckets"][1]["totals"]["income_cents"], "1");
        let v = summarize("period=year&from=2024-01-01&to=2026-12-31", [], 1).unwrap();
        assert_eq!(v["buckets"].as_array().unwrap().len(), 3);
        assert!(v["totals"]["margin"].is_null());
    }
    #[test]
    fn bad_and_unbounded_ranges_are_rejected() {
        for q in [
            "period=day&from=2025-01-01&to=2026-12-31",
            "period=day&from=2026-02-30&to=2026-03-01",
            "period=day&period=week&from=2026-01-01&to=2026-01-01",
            "period=foo&from=2026-01-01&to=2026-01-01",
            "period=day&from=2026-01-02&to=2026-01-01",
        ] {
            assert!(summarize(q, [], 1).is_err());
        }
    }
}
