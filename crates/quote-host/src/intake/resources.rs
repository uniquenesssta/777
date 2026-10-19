//! Verify the installed worker can read schema 3 before touching the live ledger.
use super::*;
struct Probe(PathBuf);
impl Drop for Probe {
    fn drop(&mut self) {
        for suffix in ["", "-wal", "-shm"] {
            let mut path = self.0.as_os_str().to_os_string();
            path.push(suffix);
            let _ = std::fs::remove_file(PathBuf::from(path));
        }
    }
}
pub(super) fn check(s: &Service) -> Result<()> {
    if s.config.get("rust_worker_sha256").is_none() {
        return Ok(());
    }
    let path = s
        .root
        .join("private")
        .join(format!(".offline-probe-{}.sqlite3", store::uid()?));
    let _owned = Probe(path.clone());
    store::create(&path)?;
    let mut c = store::open(&path, true)?;
    quote_ledger::intake::upgrade(&mut c)?;
    // A B-era worker can read an empty schema-3 probe but cannot validate the
    // complete note/state revision bases used by C. Exercise that capability.
    let actor = store::Actor {
        subject: store::uid()?,
        role: "admin".into(),
    };
    let prices = serde_json::from_value(
        serde_json::json!({"price_version_id":"application-probe","items":[{"product_id":"probe","sale":"1","cost":"0","k":"1","single":true}]}),
    )?;
    store::mutate(
        &mut c,
        store::Mutation::PublishPrices {
            request_id: store::uid()?,
            actor: actor.clone(),
            prices,
            expected_price_version_id: None,
        },
        None,
    )?;
    let snapshot = store::decode_quote(
        serde_json::json!({"price_version_id":"application-probe","lines":[{"line_kind":"normal","product_id":"probe","q":"1"}]}),
    )?;
    let order = store::mutate(
        &mut c,
        store::Mutation::SubmitOrder {
            request_id: store::uid()?,
            actor: actor.clone(),
            snapshot,
            details: serde_json::json!({"customer":"","wechat":"","order_ref":""}),
        },
        None,
    )?;
    store::mutate(
        &mut c,
        store::Mutation::AppendNote {
            request_id: store::uid()?,
            actor,
            order_id: order["order_id"].as_str().unwrap().into(),
            body: "application probe".into(),
            expected_revision: 1,
        },
        None,
    )?;
    drop(c);
    let expected = quote_ledger::integrity::inventory(&store::open(&path, false)?)?;
    let actual = crate::host::probe_worker(
        &s.root.join("private/rust-ledger-worker.exe"),
        &path,
        s.auxiliary,
    )?;
    if actual != expected {
        return Err(Error::new(503, "WORKER_RESOURCE_INCOMPATIBLE"));
    }
    Ok(())
}
