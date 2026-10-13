//! Single-owner draft transitions. A source observation is not authentication.
use crate::{calculation::calculate, models::*, numbers::trim};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
static GENERATION: AtomicU64 = AtomicU64::new(1);
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Details {
    #[serde(default)]
    pub customer: String,
    #[serde(default)]
    pub order_ref: String,
    #[serde(default)]
    pub wechat: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PriceSource {
    Current,
    Unavailable,
    Unverified,
    Invalid,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputKind {
    Excel,
    QuoteImage,
    Screenshot,
}
#[derive(Clone, Debug)]
pub struct Request {
    draft_id: String,
    generation: u64,
    revision: u64,
    snapshot: Option<Quote>,
    prices: Option<Prices>,
    details: Details,
    issues: Vec<Issue>,
}
#[derive(Clone, Debug)]
pub struct Completion {
    request: Request,
    result: QuoteResult,
}
pub fn run_calculation(request: Request) -> Completion {
    let result = if !request.issues.is_empty() {
        QuoteResult::invalid(request.snapshot.as_ref(), request.issues.clone())
    } else if let Some(q) = &request.snapshot {
        if let Some(p) = &request.prices {
            calculate(q, p)
        } else {
            QuoteResult::invalid(
                Some(q),
                vec![Issue::problem(
                    "VALIDATION",
                    "PRICE_SNAPSHOT_REQUIRED",
                    "prices",
                )],
            )
        }
    } else {
        QuoteResult::invalid(
            None,
            vec![Issue::problem(
                "VALIDATION",
                "SNAPSHOT_REQUIRED",
                "snapshot",
            )],
        )
    };
    Completion { request, result }
}
#[derive(Clone, Debug)]
pub struct Payload {
    draft_id: String,
    revision: u64,
    snapshot: Quote,
    prices: Prices,
    details: Details,
    result: QuoteResult,
}
impl Payload {
    pub fn wire(&self) -> Value {
        json!({"draft_id":self.draft_id,"revision":self.revision.to_string(),"snapshot":self.snapshot,"prices":self.prices,"details":self.details,"result":self.result.wire()})
    }
}
#[derive(Clone, Debug)]
pub struct Decision {
    pub kind: OutputKind,
    pub status: String,
    pub payload: Option<Payload>,
    pub issues: Vec<Issue>,
}
impl Decision {
    pub fn wire(&self) -> Value {
        json!({"kind":self.kind,"status":self.status,"allowed":self.status=="ok","payload":self.payload.as_ref().map(Payload::wire),"issues":self.issues})
    }
}
pub struct Session {
    draft_id: String,
    generation: u64,
    revision: u64,
    calculation_revision: Option<u64>,
    snapshot: Option<Quote>,
    prices: Option<Prices>,
    details: Details,
    result: Option<QuoteResult>,
    issues: Vec<Issue>,
    source: PriceSource,
    latest: Option<String>,
    has_calculated: bool,
    confirmation: bool,
}
fn check_latest(latest: Option<&str>) -> Result<(), Fault> {
    if let Some(s) = latest {
        if s.is_empty()
            || s != trim(s)
            || s.chars().count() > 256
            || s.chars()
                .any(|c| (c as u32) < 32 || (127..=159).contains(&(c as u32)))
        {
            return Err(Fault::new(
                "LATEST_PRICE_VERSION_INVALID",
                "latest_price_version_id",
            ));
        }
    }
    Ok(())
}
fn check_draft(id: &str) -> bool {
    id.len() == 36
        && id.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
            }
        })
        && id.bytes().any(|b| b != b'0' && b != b'-')
}
impl Session {
    pub fn new(
        draft_id: String,
        snapshot: Option<Quote>,
        prices: Option<Prices>,
        details: Details,
        source: PriceSource,
        latest: Option<String>,
    ) -> Result<Self, Fault> {
        if !check_draft(&draft_id) {
            return Err(Fault::new("DRAFT_ID_INVALID", "draft_id"));
        }
        check_latest(latest.as_deref())?;
        let generation = GENERATION
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |n| n.checked_add(1))
            .map_err(|_| Fault::new("DRAFT_CAPACITY", "draft_id"))?;
        Ok(Self {
            draft_id,
            generation,
            revision: 0,
            calculation_revision: None,
            snapshot,
            prices,
            details,
            result: None,
            issues: vec![],
            source,
            latest,
            has_calculated: false,
            confirmation: false,
        })
    }
    fn invalidate(&mut self) -> Result<(), Fault> {
        self.revision = self
            .revision
            .checked_add(1)
            .ok_or_else(|| Fault::new("REVISION_CAPACITY", "revision"))?;
        self.result = None;
        self.calculation_revision = None;
        Ok(())
    }
    pub fn update_inputs(&mut self, q: Quote, details: Option<Details>) -> Result<(), Fault> {
        self.invalidate()?;
        self.snapshot = Some(q);
        if let Some(d) = details {
            self.details = d;
        }
        self.issues.clear();
        Ok(())
    }
    pub fn update_details(&mut self, d: Details) -> Result<(), Fault> {
        self.invalidate()?;
        self.details = d;
        Ok(())
    }
    pub fn invalidate_inputs(&mut self, issues: Vec<Issue>) -> Result<(), Fault> {
        if issues.iter().any(|i| i.code != "VALIDATION") {
            return Err(Fault::new("INPUT_ISSUES_TYPE", "input_issues"));
        }
        self.invalidate()?;
        self.snapshot = None;
        self.issues = issues;
        Ok(())
    }
    pub fn observe_source(
        &mut self,
        source: PriceSource,
        latest: Option<String>,
    ) -> Result<(), Fault> {
        check_latest(latest.as_deref())?;
        if (self.source, &self.latest) != (source, &latest) {
            self.invalidate()?;
            self.source = source;
            self.latest = latest;
        }
        Ok(())
    }
    pub fn refresh_prices(&mut self, p: Prices) -> Result<(), Fault> {
        self.invalidate()?;
        self.confirmation = self.confirmation || self.prices.is_some();
        if let Some(q) = &mut self.snapshot {
            q.price_version_id = p.price_version_id.clone();
        }
        self.prices = Some(p);
        Ok(())
    }
    pub fn begin_calculation(&self) -> Request {
        Request {
            draft_id: self.draft_id.clone(),
            generation: self.generation,
            revision: self.revision,
            snapshot: self.snapshot.clone(),
            prices: self.prices.clone(),
            details: self.details.clone(),
            issues: self.issues.clone(),
        }
    }
    pub fn apply_calculation(&mut self, c: Completion) -> bool {
        let r = &c.request;
        if r.draft_id != self.draft_id
            || r.generation != self.generation
            || r.revision != self.revision
            || r.snapshot != self.snapshot
            || r.prices != self.prices
            || r.details != self.details
            || r.issues != self.issues
        {
            return false;
        }
        self.calculation_revision = Some(r.revision);
        self.result = Some(c.result);
        self.has_calculated = true;
        true
    }
    pub fn calculate(&mut self) {
        self.apply_calculation(run_calculation(self.begin_calculation()));
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn state_wire(&self) -> Value {
        let status =
            if !self.issues.is_empty() || self.result.as_ref().is_some_and(|r| r.status != "ok") {
                "invalid"
            } else if self.result.is_some() {
                "valid"
            } else if self.has_calculated {
                "stale"
            } else {
                "uncalculated"
            };
        json!({"draft_id":self.draft_id,"revision":self.revision.to_string(),"calculation_revision":self.calculation_revision.map(|n|n.to_string()),"status":status,"snapshot":self.snapshot,"prices":self.prices,"details":self.details,"result":self.result.as_ref().map(QuoteResult::wire),"input_issues":self.issues,"price_source":self.source,"latest_price_version_id":self.latest,"price_confirmation_required":self.confirmation})
    }
    fn output_problem(&self, confirmation: bool) -> Option<(String, Vec<Issue>)> {
        let problem = |code: &str, reason: &str, field: &str| {
            Some((code.into(), vec![Issue::problem(code, reason, field)]))
        };
        if !self.issues.is_empty() {
            return Some(("VALIDATION".into(), self.issues.clone()));
        }
        if let Some(r) = &self.result {
            if r.status != "ok" {
                return Some(("VALIDATION".into(), r.issues.clone()));
            }
        }
        if self.source == PriceSource::Unavailable {
            return problem("IO_UNAVAILABLE", "PRICES_UNAVAILABLE", "price_source");
        }
        if self.source != PriceSource::Current || self.latest.is_none() {
            return problem(
                "VALIDATION",
                if self.source == PriceSource::Invalid {
                    "PRICE_CONFIG_INVALID"
                } else {
                    "PRICE_SOURCE_UNVERIFIED"
                },
                "price_source",
            );
        }
        let Some(p) = &self.prices else {
            return problem("VALIDATION", "PRICE_SNAPSHOT_REQUIRED", "prices");
        };
        if p.price_version_id.as_str() != self.latest.as_deref() {
            return problem("PRICE_STALE", "PRICE_VERSION_CHANGED", "price_version_id");
        }
        let (Some(q), Some(r)) = (&self.snapshot, &self.result) else {
            return problem(
                if self.has_calculated {
                    "CALCULATION_STALE"
                } else {
                    "VALIDATION"
                },
                "CALCULATION_REQUIRED",
                "calculation_revision",
            );
        };
        if self.calculation_revision != Some(self.revision) {
            return problem(
                if self.has_calculated {
                    "CALCULATION_STALE"
                } else {
                    "VALIDATION"
                },
                "CALCULATION_REQUIRED",
                "calculation_revision",
            );
        }
        if r.price_version_id != q.price_version_id
            || r.price_version_id.as_str() != self.latest.as_deref()
            || r.rule_version != q.rule_version
            || r.numeric_profile != q.numeric_profile
        {
            return problem(
                "CALCULATION_STALE",
                "RESULT_VERSION_MISMATCH",
                "calculation_revision",
            );
        }
        let (Some(lines), Some(totals)) = (&r.lines, &r.totals) else {
            return problem("VALIDATION", "RESULT_INCOMPLETE", "lines");
        };
        if lines.is_empty() || lines.len() != q.lines.len() {
            return problem("VALIDATION", "RESULT_INCOMPLETE", "lines");
        }
        if lines
            .iter()
            .zip(&q.lines)
            .enumerate()
            .any(|(i, (line, raw))| line.sequence != i + 1 || line.raw != *raw)
            || lines
                .iter()
                .map(|l| l.amounts.income() as i128)
                .sum::<i128>()
                != totals.income() as i128
            || lines.iter().map(|l| l.amounts.cost() as i128).sum::<i128>() != totals.cost() as i128
        {
            return problem("VALIDATION", "RESULT_INCONSISTENT", "lines");
        }
        if confirmation && self.confirmation {
            return problem(
                "VALIDATION",
                "PRICE_CONFIRMATION_REQUIRED",
                "price_version_id",
            );
        }
        None
    }
    pub fn confirm_prices(&mut self, expected: u64) -> bool {
        if expected != self.revision || self.output_problem(false).is_some() {
            return false;
        }
        self.confirmation = false;
        true
    }
    pub fn prepare_output(&self, kind: OutputKind) -> Decision {
        if let Some((status, issues)) = self.output_problem(true) {
            return Decision {
                kind,
                status,
                payload: None,
                issues,
            };
        }
        Decision {
            kind,
            status: "ok".into(),
            payload: Some(Payload {
                draft_id: self.draft_id.clone(),
                revision: self.revision,
                snapshot: self.snapshot.clone().unwrap(),
                prices: self.prices.clone().unwrap(),
                details: self.details.clone(),
                result: self.result.clone().unwrap(),
            }),
            issues: vec![],
        }
    }
    pub fn dispatch_output<T>(
        &self,
        kind: OutputKind,
        writer: impl FnOnce(&Payload) -> T,
    ) -> Result<T, Box<Decision>> {
        let decision = self.prepare_output(kind);
        match &decision.payload {
            Some(payload) => Ok(writer(payload)),
            None => Err(Box::new(decision)),
        }
    }
}

#[cfg(test)]
mod integrity_tests {
    use super::*;
    fn ready() -> Session {
        let q = serde_json::from_value(
            json!({"price_version_id":"v1","lines":[{"kind":"normal","product_id":"P","q":"1"}]}),
        )
        .unwrap();
        let p=serde_json::from_value(json!({"price_version_id":"v1","items":[{"product_id":"P","sale":"10","cost":"4","single":true}]})).unwrap();
        let mut s = Session::new(
            "5d782c12-60bd-421a-9f12-a3e9fe819d03".into(),
            Some(q),
            Some(p),
            Details::default(),
            PriceSource::Current,
            Some("v1".into()),
        )
        .unwrap();
        s.calculate();
        s
    }
    #[test]
    fn incomplete_results_are_blocked() {
        let mut s = ready();
        s.result.as_mut().unwrap().lines = None;
        assert_eq!(
            s.prepare_output(OutputKind::Excel).issues[0].reason,
            "RESULT_INCOMPLETE"
        );
    }
    #[test]
    fn incorrect_result_versions_are_blocked() {
        let mut s = ready();
        s.result.as_mut().unwrap().rule_version = json!("wrong");
        assert_eq!(
            s.prepare_output(OutputKind::Excel).issues[0].reason,
            "RESULT_VERSION_MISMATCH"
        );
    }
    #[test]
    fn incorrect_result_totals_are_blocked() {
        let mut s = ready();
        s.result.as_mut().unwrap().totals = Some(Amounts::new(1, 0, false).unwrap());
        assert_eq!(
            s.prepare_output(OutputKind::Excel).issues[0].reason,
            "RESULT_INCONSISTENT"
        );
    }
    #[test]
    fn invalid_observation_is_atomic() {
        let mut s = ready();
        let before = s.state_wire();
        assert!(s
            .observe_source(PriceSource::Current, Some(" v1 ".into()))
            .is_err());
        assert_eq!(s.state_wire(), before);
    }
    #[test]
    fn revision_overflow_is_atomic() {
        let mut s = ready();
        s.revision = u64::MAX;
        let before = s.state_wire();
        assert!(s.update_details(Details::default()).is_err());
        assert_eq!(s.state_wire(), before);
    }
}
