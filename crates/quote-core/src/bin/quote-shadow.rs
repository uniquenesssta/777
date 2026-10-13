//! Isolated JSON-lines verification adapter, not an authenticated service.
use quote_core::{
    calculation::calculate,
    configuration::{self, Source},
    models::*,
    numbers,
    session::*,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::{self, BufRead, Read, Write},
};
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Calculate {
        snapshot: Quote,
        prices: Prices,
    },
    Number {
        raw: Value,
        #[serde(default)]
        field: String,
        #[serde(default)]
        empty_k: bool,
    },
    Percent {
        raw: Value,
    },
    Config {
        source: Value,
        #[serde(default)]
        source_bytes: Option<Vec<u8>>,
        price_version_id: Value,
        #[serde(default)]
        legacy_single_names: Option<Value>,
    },
    ConfigRefresh {
        steps: Vec<ConfigStep>,
    },
    Session {
        draft_id: String,
        #[serde(default)]
        snapshot: Option<Quote>,
        #[serde(default)]
        prices: Option<Prices>,
        #[serde(default)]
        details: Details,
        #[serde(default = "unverified")]
        price_source: PriceSource,
        #[serde(default)]
        latest_price_version_id: Option<String>,
        actions: Vec<Value>,
    },
}
fn unverified() -> PriceSource {
    PriceSource::Unverified
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigStep {
    source: Value,
    price_version_id: Value,
    #[serde(default)]
    legacy_single_names: Option<Value>,
}
#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Calculate,
    UpdateInputs {
        snapshot: Quote,
        #[serde(default)]
        details: Option<Details>,
    },
    UpdateDetails {
        details: Details,
    },
    InvalidateInputs {
        #[serde(default)]
        issues: Vec<Issue>,
    },
    ObserveSource {
        price_source: PriceSource,
        #[serde(default)]
        latest_price_version_id: Option<String>,
    },
    RefreshPrices {
        prices: Prices,
    },
    Begin {
        key: String,
    },
    Apply {
        key: String,
    },
    Foreign {
        key: String,
    },
    Confirm {
        expected_revision: String,
    },
    Dispatch {
        kind: OutputKind,
    },
    WriterError {
        kind: OutputKind,
    },
}
fn invalid(f: Fault) -> Value {
    json!({"status":"VALIDATION","issues":[Issue::validation(f,None)]})
}
fn handle(c: Command) -> Result<Value, Fault> {
    Ok(match c {
        Command::Calculate { snapshot, prices } => calculate(&snapshot, &prices).wire(),
        Command::Number {
            raw,
            field,
            empty_k,
        } => match numbers::parse_number(&raw, &field, empty_k) {
            Ok(n) => json!({"status":"ok","value":n.text()}),
            Err(f) => invalid(f),
        },
        Command::Percent { raw } => match numbers::parse_percent(&raw) {
            Ok(n) => json!({"status":"ok","value":n.text()}),
            Err(f) => invalid(f),
        },
        Command::Config {
            source,
            source_bytes,
            price_version_id,
            legacy_single_names,
        } => {
            let source = if let Some(b) = &source_bytes {
                Source::Bytes(b)
            } else if let Some(s) = source.as_str() {
                Source::Text(s)
            } else {
                Source::Invalid
            };
            configuration::parse_config(source, &price_version_id, legacy_single_names.as_ref())
                .wire()
        }
        Command::ConfigRefresh { steps } => {
            if steps.len() > 1000 {
                return Err(Fault::new("WIRE_CAPACITY", "steps"));
            }
            let mut active = None;
            let mut out = vec![];
            for step in steps {
                let source = step.source.as_str().map_or(Source::Invalid, Source::Text);
                let validation = configuration::parse_config(
                    source,
                    &step.price_version_id,
                    step.legacy_single_names.as_ref(),
                );
                let (a, v) = configuration::refresh_config(active, validation);
                active = a;
                out.push(json!({"applied":v.status=="ok","active":active.as_ref().map(configuration::Config::wire),"validation":v.wire()}));
            }
            json!(out)
        }
        Command::Session {
            draft_id,
            snapshot,
            prices,
            details,
            price_source,
            latest_price_version_id,
            actions,
        } => {
            if actions.len() > 1000 {
                return Err(Fault::new("WIRE_CAPACITY", "actions"));
            }
            let mut s = Session::new(
                draft_id.clone(),
                snapshot,
                prices,
                details,
                price_source,
                latest_price_version_id,
            )?;
            let mut requests = HashMap::new();
            let mut history = vec![];
            let mut calls = 0;
            let mut payloads = vec![];
            history.push(observe(&s, Value::Null, calls, &payloads));
            for action in actions {
                let result = match serde_json::from_value::<Action>(action) {
                    Err(_) => invalid(Fault::new("WIRE_SCHEMA", "action")),
                    Ok(a) => {
                        let run = || -> Result<Value, Fault> {
                            Ok(match a {
                                Action::Calculate => {
                                    s.calculate();
                                    Value::Null
                                }
                                Action::UpdateInputs { snapshot, details } => {
                                    s.update_inputs(snapshot, details)?;
                                    Value::Null
                                }
                                Action::UpdateDetails { details } => {
                                    s.update_details(details)?;
                                    Value::Null
                                }
                                Action::InvalidateInputs { issues } => {
                                    s.invalidate_inputs(issues)?;
                                    Value::Null
                                }
                                Action::ObserveSource {
                                    price_source,
                                    latest_price_version_id,
                                } => {
                                    s.observe_source(price_source, latest_price_version_id)?;
                                    Value::Null
                                }
                                Action::RefreshPrices { prices } => {
                                    s.refresh_prices(prices)?;
                                    Value::Null
                                }
                                Action::Begin { key } => {
                                    requests.insert(key, s.begin_calculation());
                                    Value::Null
                                }
                                Action::Foreign { key } => {
                                    let other = Session::new(
                                        draft_id.clone(),
                                        None,
                                        None,
                                        Details::default(),
                                        PriceSource::Unverified,
                                        None,
                                    )?;
                                    requests.insert(key, other.begin_calculation());
                                    Value::Null
                                }
                                Action::Apply { key } => {
                                    let r = requests
                                        .get(&key)
                                        .ok_or_else(|| Fault::new("REQUEST_UNKNOWN", "key"))?
                                        .clone();
                                    json!(s.apply_calculation(run_calculation(r)))
                                }
                                Action::Confirm { expected_revision } => {
                                    if expected_revision.is_empty()
                                        || !expected_revision.bytes().all(|b| b.is_ascii_digit())
                                        || expected_revision.len() > 1
                                            && expected_revision.starts_with('0')
                                    {
                                        return Err(Fault::new(
                                            "REVISION_INVALID",
                                            "expected_revision",
                                        ));
                                    }
                                    json!(s.confirm_prices(
                                        expected_revision.parse::<u64>().map_err(
                                            |_| Fault::new("REVISION_INVALID", "expected_revision")
                                        )?
                                    ))
                                }
                                Action::Dispatch { kind } => match s.dispatch_output(kind, |p| {
                                    calls += 1;
                                    payloads.push(p.wire());
                                    p.wire()
                                }) {
                                    Ok(p) => json!({"status":"ok","payload":p}),
                                    Err(d) => d.wire(),
                                },
                                Action::WriterError { kind } => {
                                    match s.dispatch_output(kind, |_| {
                                        calls += 1;
                                        Err::<(), _>("synthetic writer failure")
                                    }) {
                                        Ok(Err(_)) => json!({"status":"WRITER_FAILURE"}),
                                        Ok(Ok(_)) => unreachable!(),
                                        Err(d) => d.wire(),
                                    }
                                }
                            })
                        };
                        match run() {
                            Ok(v) => v,
                            Err(f) => invalid(f),
                        }
                    }
                };
                history.push(observe(&s, result, calls, &payloads));
            }
            json!(history)
        }
    })
}
fn observe(s: &Session, result: Value, calls: usize, payloads: &[Value]) -> Value {
    json!({"state":s.state_wire(),"action_result":result,"decisions":[s.prepare_output(OutputKind::Excel).wire(),s.prepare_output(OutputKind::QuoteImage).wire(),s.prepare_output(OutputKind::Screenshot).wire()],"writer_calls":calls,"written_payloads":payloads})
}
fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let mut input = stdin.lock();
    let stdout = io::stdout();
    let mut output = stdout.lock();
    loop {
        let mut line = Vec::new();
        let n = input
            .by_ref()
            .take(16 * 1024 * 1024 + 1)
            .read_until(b'\n', &mut line)?;
        if n == 0 {
            break;
        }
        if n > 16 * 1024 * 1024 {
            writeln!(
                output,
                "{}",
                invalid(Fault::new("WIRE_CAPACITY", "request"))
            )?;
            break;
        }
        let result = match serde_json::from_slice::<Command>(&line) {
            Ok(c) => handle(c).unwrap_or_else(invalid),
            Err(_) => invalid(Fault::new("WIRE_SCHEMA", "request")),
        };
        serde_json::to_writer(&mut output, &result)?;
        writeln!(output)?;
        output.flush()?;
    }
    Ok(())
}
