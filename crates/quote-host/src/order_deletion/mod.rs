//! Developer-only order cleanup on the authenticated ledger, including immutable deletion history.
mod history;
use crate::{auth::Auth, fail, protocol, service::Service, Result};
use quote_ledger::{deletion, store};
use serde_json::{json, Value};
pub fn handle(
    s: &mut Service,
    method: &str,
    path: &str,
    token: &str,
    data: &Value,
) -> Result<Value> {
    let actor = s.auth.authenticate(token)?;
    Auth::admin(&actor)?;
    if method != "POST" {
        return fail(404, "NOT_FOUND");
    }
    let c = store::open(&s.ledger, false)?;
    let ledger = store::verify(&c)?["ledger_id"].clone();
    match path {
        "/v1/developer/orders/list" => {
            protocol::fields(data, &["query", "offset", "history"], &[])?;
            let offset = crate::number(&data["offset"])?;
            if !(0..=1000000).contains(&offset) || !data["history"].is_boolean() {
                return fail(422, "INVALID_QUERY");
            }
            let query = protocol::text(&data["query"], 256, false)?;
            let mut result = if data["history"] == true {
                history::list(&c, query, offset)?
            } else {
                let mut args = form_urlencoded::Serializer::new(String::new());
                args.append_pair("q", query)
                    .append_pair("offset", &offset.to_string())
                    .append_pair("limit", "20");
                s.queries.listing(&s.ledger, &actor, &args.finish())?
            };
            result["ledger_id"] = ledger;
            Ok(result)
        }
        "/v1/developer/orders/delete" => {
            protocol::fields(
                data,
                &[
                    "ledger_id",
                    "request_id",
                    "order_id",
                    "expected_revision",
                    "reason",
                ],
                &[],
            )?;
            if data["ledger_id"] != ledger {
                return fail(409, "ORDER_DELETE_LEDGER_CHANGED");
            }
            drop(c);
            let result = deletion::delete(
                &mut store::open(&s.ledger, true)?,
                &actor,
                protocol::text(&data["request_id"], 36, true)?,
                protocol::text(&data["order_id"], 36, true)?,
                crate::number(&data["expected_revision"])?,
                protocol::text(&data["reason"], 512, true)?,
            )?;
            Ok(json!({"ledger_id":ledger,"result":result}))
        }
        _ => fail(404, "NOT_FOUND"),
    }
}
