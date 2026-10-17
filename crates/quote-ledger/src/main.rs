//! One private bounded request per native process; never opens a listening socket.
use quote_ledger::{integrity, store::*, Error, Result};
use serde_json::{json, Value};
use std::{
    io::{self, Read},
    path::Path,
};
fn run(path: &Path, input: Value, crash: Option<&str>) -> Result<Value> {
    let op = input["op"]
        .as_str()
        .ok_or_else(|| Error::new("VALIDATION"))?;
    if op == "xlsx_capabilities" {
        return Ok(
            json!({"implementation":"quote-excel-v1","formats":["777-excel-read-v1","777-output-v1"]}),
        );
    }
    if matches!(op, "xlsx_read" | "xlsx_write") {
        return Ok(quote_excel::dispatch(&input));
    }
    if op == "create" {
        return create(path);
    }
    if op == "backup" {
        let target = input["target"]
            .as_str()
            .ok_or_else(|| Error::new("VALIDATION"))?;
        return integrity::backup(path, Path::new(target));
    }
    if op == "inventory" {
        let c = open(path, false)?;
        c.execute_batch("BEGIN")?;
        return integrity::inventory(&c);
    }
    if op == "query_request" {
        let actor: Actor =
            serde_json::from_value(input["actor"].clone()).map_err(|_| Error::new("VALIDATION"))?;
        return query_request(
            &open(path, false)?,
            input["request_id"]
                .as_str()
                .ok_or_else(|| Error::new("VALIDATION"))?,
            &actor,
        );
    }
    if op == "calculate" {
        let q: quote_core::models::Quote = serde_json::from_value(input["snapshot"].clone())
            .map_err(|_| Error::new("VALIDATION"))?;
        let c = open(path, false)?;
        c.execute_batch("BEGIN")?;
        let p = active_prices(&c)?;
        if q.price_version_id != p.price_version_id {
            return Err(Error::new("CONFLICT"));
        }
        return Ok(quote_core::calculation::calculate(&q, &p).wire());
    }
    if op == "active_prices" {
        return Ok(serde_json::to_value(active_prices(&open(path, false)?)?)?);
    }
    if op == "import_apply" {
        let actor: Actor =
            serde_json::from_value(input["actor"].clone()).map_err(|_| Error::new("VALIDATION"))?;
        return integrity::apply_import(&mut open(path, true)?, &actor, &input["delta"], crash);
    }
    let m: Mutation = serde_json::from_value(input).map_err(|_| Error::new("VALIDATION"))?;
    mutate(&mut open(path, true)?, m, crash)
}
fn main() {
    quote_diagnostics::init("ledger");
    let args: Vec<String> = std::env::args().collect();
    let mut allowed = cfg!(windows);
    let mut crash = None;
    for a in args.iter().skip(2) {
        if a == "--auxiliary" && !cfg!(windows) {
            allowed = true;
        } else if let Some(f) = a.strip_prefix("--test-fault=") {
            crash = Some(f);
        } else {
            println!("{}", json!({"ok":false,"error":"ARGUMENT_INVALID"}));
            return;
        }
    }
    let result = if args.len() < 2 || !allowed {
        Err(Error::new("WINDOWS_REQUIRED"))
    } else {
        let mut bytes = Vec::new();
        match io::stdin()
            .take(128 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)
        {
            Ok(n) if n <= 128 * 1024 * 1024 => match serde_json::from_slice(&bytes) {
                Ok(v) => run(Path::new(&args[1]), v, crash),
                Err(_) => Err(Error::new("VALIDATION")),
            },
            _ => Err(Error::new("CAPACITY")),
        }
    };
    quote_diagnostics::event(
        "runtime.stop",
        json!({"error":result.as_ref().err().map(|e|&e.code)}),
    );
    println!(
        "{}",
        match result {
            Ok(v) => json!({"ok":true,"result":v}),
            Err(e) => json!({"ok":false,"error":e.code}),
        }
    );
}
