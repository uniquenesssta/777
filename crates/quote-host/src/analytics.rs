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
#[derive(Default)]
struct Bucket {
    totals: Totals,
    // Equal instants form one observation, independent of cache/hash-map order.
    profits: BTreeMap<OffsetDateTime, BigInt>,
}
impl Bucket {
    fn value(self, opening: &mut BigInt) -> Value {
        let open = opening.clone();
        let mut high = open.clone();
        let mut low = open.clone();
        for profit in self.profits.into_values() {
            *opening += profit;
            high = high.max(opening.clone());
            low = low.min(opening.clone());
        }
        json!({"totals":self.totals.value(),"profit_ohlc":{"open_cents":open.to_string(),"high_cents":high.to_string(),"low_cents":low.to_string(),"close_cents":opening.to_string()}})
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
fn bound(raw: &str, end: bool, offset: UtcOffset) -> Result<OffsetDateTime> {
    if raw.len() == 10 {
        let day = date(raw)?;
        let value = if end {
            day.with_hms_nano(23, 59, 59, 999_999_999)
        } else {
            day.with_hms_nano(0, 0, 0, 0)
        };
        return value
            .map(|v| v.assume_offset(offset))
            .map_err(|_| invalid());
    }
    if ![19, 23].contains(&raw.len()) || raw.as_bytes().get(10) != Some(&b'T') {
        return Err(invalid());
    }
    date(raw.get(..10).ok_or_else(invalid)?)?;
    OffsetDateTime::parse(&format!("{raw}+08:00"), &Rfc3339).map_err(|_| invalid())
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
    let from_raw = get("from")?;
    let to_raw = get("to")?;
    let offset = UtcOffset::from_hms(8, 0, 0).map_err(|_| invalid())?;
    let from = bound(from_raw, false, offset)?;
    let to = bound(to_raw, true, offset)?;
    if from > to {
        return Err(invalid());
    }
    let mut buckets = BTreeMap::new();
    let mut d = key(from.date(), period)?;
    let end = key(to.date(), period)?;
    loop {
        if buckets.len() >= 400 {
            return fail(422, "ANALYTICS_RANGE_TOO_LARGE");
        }
        buckets.insert(d, Bucket::default());
        if d == end {
            break;
        }
        d = next(d, period)?;
    }
    let legacy = time::format_description::parse("[year]-[month]-[day] [hour]:[minute]:[second]")
        .map_err(|_| invalid())?;
    let mut total = Totals::default();
    let mut unplaced = 0u64;
    for (raw, money) in rows {
        let parsed = OffsetDateTime::parse(raw, &Rfc3339)
            .map(|v| v.to_offset(offset))
            .or_else(|_| {
                time::PrimitiveDateTime::parse(raw, &legacy).map(|v| v.assume_offset(offset))
            });
        let Ok(instant) = parsed else {
            unplaced += 1;
            continue;
        };
        if instant < from || instant > to {
            continue;
        }
        if let Some(bucket) = buckets.get_mut(&key(instant.date(), period)?) {
            bucket.totals.add(money);
            *bucket.profits.entry(instant).or_default() += money[2];
            total.add(money);
        }
    }
    let mut opening = BigInt::from(0);
    let buckets = buckets
        .into_iter()
        .map(|(day, bucket)| {
            let mut value = bucket.value(&mut opening);
            value["start"] = json!(day.to_string());
            value
        })
        .collect::<Vec<_>>();
    Ok(
        json!({"format":"777-profit-analysis-v1","timezone":"Asia/Shanghai","week_starts_on":"Monday","period":period,"from":from_raw,"to":to_raw,"ledger_revision":revision.to_string(),"unplaced_date_orders":unplaced,"totals":total.value(),"buckets":buckets}),
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
            "period=day&from=2026-01-01T24:00:00.000&to=2026-01-02T00:00:00.000",
            "period=day&from=2026-01-01T14:01:00.000&to=2026-01-01T14:00:00.000",
            "period=day&from=2026-01-01T14:00:00.00Z&to=2026-01-01T15:00:00.000",
        ] {
            assert!(summarize(q, [], 1).is_err());
        }
    }
    #[test]
    fn rolling_time_cutoffs_exclude_the_rest_of_the_boundary_days() {
        let v = summarize(
            "period=day&from=2026-10-14T14:41:10.123&to=2026-10-15T14:41:10.123",
            [
                ("2026-10-14T06:41:10.122999Z", [900, 0, 900]),
                ("2026-10-14T06:41:10.123Z", [100, 20, 80]),
                ("2026-10-15 10:00:00", [200, 50, 150]),
                ("2026-10-15T06:41:10.123Z", [300, 100, 200]),
                ("2026-10-15T06:41:10.123001Z", [900, 0, 900]),
            ],
            1,
        )
        .unwrap();
        assert_eq!(v["totals"]["order_count"], 3);
        assert_eq!(v["totals"]["income_cents"], "600");
        assert_eq!(v["buckets"][0]["totals"]["income_cents"], "100");
        assert_eq!(v["buckets"][1]["totals"]["income_cents"], "500");
        assert_eq!(v["from"], "2026-10-14T14:41:10.123");
        assert_eq!(v["to"], "2026-10-15T14:41:10.123");
        assert_eq!(v["buckets"][1]["profit_ohlc"]["close_cents"], "430");
    }
    #[test]
    fn cumulative_candles_sort_instants_merge_ties_and_carry_empty_buckets() {
        let rows = [
            ("2026-01-03T03:00:00+08:00", [100, 0, 100]),
            ("2026-01-01T02:00:00+08:00", [0, 180, -180]),
            ("2026-01-03T02:00:00+08:00", [200, 0, 200]),
            ("2026-01-01T01:00:00+08:00", [100, 0, 100]),
            ("2026-01-02T18:00:00Z", [0, 500, -500]),
            ("2026-01-01T03:00:00+08:00", [50, 0, 50]),
        ];
        let q = "period=day&from=2026-01-01&to=2026-01-03";
        let value = summarize(q, rows, 1).unwrap();
        assert_eq!(value, summarize(q, rows.into_iter().rev(), 1).unwrap());
        for (i, expected) in [
            ["0", "100", "-80", "-30"],
            ["-30", "-30", "-30", "-30"],
            ["-30", "-30", "-330", "-230"],
        ]
        .into_iter()
        .enumerate()
        {
            for (field, amount) in ["open_cents", "high_cents", "low_cents", "close_cents"]
                .into_iter()
                .zip(expected)
            {
                assert_eq!(value["buckets"][i]["profit_ohlc"][field], amount);
            }
        }
        assert_eq!(value["buckets"][1]["totals"]["order_count"], 0);
        assert_eq!(value["totals"]["profit_cents"], "-230");
    }
    #[test]
    fn candle_accumulates_beyond_i64_and_respects_exact_window() {
        let v = summarize(
            "period=day&from=2026-01-01T10:00:00.000&to=2026-01-01T12:00:00.000",
            [
                ("2026-01-01T09:59:59+08:00", [0, 99, -99]),
                ("2026-01-01T10:00:00+08:00", [i64::MAX, 0, i64::MAX]),
                ("2026-01-01T11:00:00+08:00", [i64::MAX, 0, i64::MAX]),
                ("2026-01-01T12:00:00.001+08:00", [0, 99, -99]),
            ],
            1,
        )
        .unwrap();
        assert_eq!(
            v["buckets"][0]["profit_ohlc"],
            json!({"open_cents":"0","high_cents":"18446744073709551614","low_cents":"0","close_cents":"18446744073709551614"})
        );
        assert_eq!(v["totals"]["order_count"], 2);
    }
}
