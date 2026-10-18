use crate::{
    auth::Auth,
    backup, fail, files, number,
    outputs::{Outputs, Work},
    protocol::{self, fields, text},
    query::Queries,
    Error, Result,
};
use quote_core::{
    calculation::calculate,
    models::{NUMERIC_PROFILE, RULE_VERSION},
};
use quote_ledger::{
    integrity,
    store::{self, Actor, Mutation},
};
use rusqlite::OptionalExtension;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
pub struct Service {
    pub root: PathBuf,
    pub config: Value,
    pub ledger: PathBuf,
    pub auth: Auth,
    pub devices: Option<crate::devices::Devices>,
    pub outputs: Option<Outputs>,
    pub queries: Queries,
    pub auxiliary: bool,
    pub font: Option<PathBuf>,
    pub test_fault: Option<PathBuf>,
}
impl Service {
    pub fn load(root: &Path, auxiliary: bool, maintenance: bool) -> Result<Self> {
        if !cfg!(windows) && !auxiliary {
            return fail(400, "WINDOWS_HOST_REQUIRED");
        }
        if cfg!(windows) && auxiliary {
            return fail(400, "WINDOWS_SECURITY_CANNOT_BE_DISABLED");
        }
        files::dir(root)?;
        let private = root.join("private");
        files::dir(&private)?;
        let config = files::read_json(&private.join("service.json"))?;
        fields(
            &config,
            &[
                "schema",
                "ledger_id",
                "backup_store_id",
                "backup_dir",
                "bind",
                "port",
                "certificate_sha256",
                "private_security",
                "maintenance",
            ],
            &[
                "ledger_backend",
                "rust_worker_sha256",
                "service_backend",
                "rust_host_sha256",
                "device_auth",
            ],
        )?;
        if config["schema"] != "777-host-v1"
            || !config["maintenance"].is_boolean()
            || !(1..=65535).contains(&number(&config["port"])?)
            || config["bind"]
                .as_str()
                .is_none_or(|s| s.parse::<std::net::IpAddr>().is_err())
        {
            return fail(422, "HOST_CONFIG_INVALID");
        }
        if config["maintenance"] == true && !maintenance {
            return fail(503, "RECOVERY_MAINTENANCE_REQUIRED");
        }
        let data = crate::cluster::replica::data_directory(root)?;
        let ledger = data.join("ledger.sqlite3");
        let c = store::open(&ledger, false)?;
        let inventory = integrity::inventory(&c)?;
        if inventory["ledger_id"] != config["ledger_id"] {
            return fail(503, "HOST_STORE_IDENTITY_CONFLICT");
        }
        crate::host::validate_resources(&private, &config)?;
        if crate::host::certificate_sha(&private.join("tls-cert.pem"))?
            != config["certificate_sha256"]
        {
            return fail(503, "CERTIFICATE_IDENTITY_CONFLICT");
        }
        files::local(&private.join("tls-key.pem"), true)?;
        let auth = Auth::open(data.join("auth.sqlite3"))?;
        let devices = match config.get("device_auth") {
            None => None,
            Some(v) if v == crate::devices::FORMAT => {
                Some(crate::devices::Devices::open(data.join("devices.sqlite3"))?)
            }
            _ => return fail(409, "DEVICE_PROTOCOL_CONFLICT"),
        };
        if let Some(d) = &devices {
            d.validate_accounts(&auth)?;
        }
        let outputs = if data.join("outputs.sqlite3").exists() {
            Some(Outputs::open(
                data.join("outputs.sqlite3"),
                config["ledger_id"]
                    .as_str()
                    .ok_or_else(|| Error::new(422, "HOST_CONFIG_INVALID"))?,
            )?)
        } else {
            None
        };
        let font = if cfg!(windows) {
            std::env::var_os("WINDIR").map(PathBuf::from).and_then(|p| {
                [p.join("Fonts/msyh.ttc"), p.join("Fonts/simhei.ttf")]
                    .into_iter()
                    .find(|p| p.is_file())
            })
        } else {
            None
        };
        // v1 upgrade is atomic and occurs only after validating this service and resources.
        if data == private {
            drop(store::open(&ledger, true)?);
        }
        Ok(Self {
            root: root.into(),
            config,
            ledger,
            auth,
            devices,
            outputs,
            queries: Queries::new()?,
            auxiliary,
            font,
            test_fault: None,
        })
    }
    pub fn order(&self, a: &Actor, key: &str) -> Result<Value> {
        let c = store::open(&self.ledger, false)?;
        c.execute_batch("BEGIN")?;
        Self::order_on(&c, a, key, true)
    }
    fn order_on(
        c: &rusqlite::Connection,
        a: &Actor,
        key: &str,
        include_history: bool,
    ) -> Result<Value> {
        let value=c.query_row("SELECT owner_id,revision,state,price_id,created_at,rule_version,numeric_profile,details_json,income_cents,cost_cents,profit_cents FROM orders WHERE order_id=?",[key],|r|Ok((r.get::<_,String>(0)?,json!({"order_id":key,"revision":r.get::<_,i64>(1)?,"state":r.get::<_,String>(2)?,"price_version_id":r.get::<_,String>(3)?,"created_at":r.get::<_,String>(4)?,"rule_version":r.get::<_,String>(5)?,"numeric_profile":r.get::<_,String>(6)?,"details":serde_json::from_str::<Value>(&r.get::<_,String>(7)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"income_cents":r.get::<_,i64>(8)?.to_string(),"cost_cents":r.get::<_,i64>(9)?.to_string(),"profit_cents":r.get::<_,i64>(10)?.to_string()})))).optional()?;
        let (owner, mut v) = value.ok_or_else(|| Error::new(404, "NOT_FOUND"))?;
        if a.role != "admin" && owner != a.subject {
            return fail(404, "NOT_FOUND");
        }
        if a.role == "admin" {
            v["owner_id"] = json!(owner)
        } else {
            v.as_object_mut().unwrap().remove("cost_cents");
            v.as_object_mut().unwrap().remove("profit_cents");
        }
        let mut st=c.prepare("SELECT sequence,raw_json,normalized_json,subtotal_before_cents,income_cents,cost_cents,profit_cents FROM lines WHERE order_id=? ORDER BY sequence")?;
        let lines=st.query_map([key],|r|{let mut n=serde_json::from_str::<Value>(&r.get::<_,String>(2)?).map_err(|_|rusqlite::Error::InvalidQuery)?;protocol::normalized(&mut n,a);let f=protocol::financial(json!({"income_cents":r.get::<_,i64>(4)?.to_string(),"cost_cents":r.get::<_,i64>(5)?.to_string(),"profit_cents":r.get::<_,i64>(6)?.to_string()}),a);let mut l=json!({"sequence":r.get::<_,i64>(0)?,"raw":serde_json::from_str::<Value>(&r.get::<_,String>(1)?).map_err(|_|rusqlite::Error::InvalidQuery)?,"normalized":n,"subtotal_before_cents":r.get::<_,i64>(3)?.to_string()});l.as_object_mut().unwrap().extend(f.as_object().unwrap().clone());Ok(l)})?.collect::<std::result::Result<Vec<_>,_>>()?;
        v["lines"] = json!(lines);
        let ids = quote_ledger::editing::object_rows(
            c,
            "SELECT line_id FROM lines WHERE order_id=? ORDER BY sequence",
            key,
        )?;
        for (line, id) in v["lines"].as_array_mut().unwrap().iter_mut().zip(ids) {
            line["line_id"] = id["line_id"].clone();
        }
        v["customer_id"] = c
            .query_row(
                "SELECT customer_id FROM orders WHERE order_id=?",
                [key],
                |r| r.get::<_, Option<String>>(0),
            )?
            .map_or(Value::Null, Value::String);
        if include_history {
            let history=quote_ledger::editing::object_rows(c,"SELECT revision,snapshot_json,created_at,actor_id FROM order_versions WHERE order_id=? ORDER BY revision DESC",key)?;
            let mut versions = vec![];
            for h in history {
                let rev = h["revision"]
                    .as_i64()
                    .ok_or_else(|| Error::new(503, "INVALID_DATABASE"))?;
                let snap = quote_ledger::editing::validate_archive(
                    c,
                    key,
                    rev,
                    h["snapshot_json"]
                        .as_str()
                        .ok_or_else(|| Error::new(503, "INVALID_DATABASE"))?,
                )?;
                let o = &snap["order"];
                versions.push(protocol::financial(json!({"revision":rev.to_string(),"created_at":h["created_at"],"details":serde_json::from_str::<Value>(o["details_json"].as_str().ok_or_else(||Error::new(503,"INVALID_DATABASE"))?)?,"income_cents":o["income_cents"].to_string(),"cost_cents":o["cost_cents"].to_string(),"profit_cents":o["profit_cents"].to_string()}),a));
            }
            v["history"] = json!(versions);
        }
        let mut st=c.prepare("SELECT note_id,author_id,body,created_at FROM notes WHERE order_id=? ORDER BY created_at,note_id")?;
        let notes=st.query_map([key],|r|Ok(json!({"note_id":r.get::<_,String>(0)?,"author":r.get::<_,String>(1)?,"body":r.get::<_,String>(2)?,"created_at":r.get::<_,String>(3)?})))?.collect::<std::result::Result<Vec<_>,_>>()?;
        v["notes"] = json!(notes);
        v["updated_at"] = json!(c.query_row(
            "SELECT max(created_at) FROM audit_events WHERE order_id=?",
            [key],
            |r| r.get::<_, Option<String>>(0)
        )?);
        Ok(v)
    }
    pub fn prepare_output(&self) -> Result<Option<Work>> {
        if crate::cluster::config::read(&self.root)?
            .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
        {
            return Ok(None);
        }
        match &self.outputs {
            Some(o) => o.prepare(&self.auth, self.font.clone()),
            None => Ok(None),
        }
    }
    fn mutate(&self, m: Mutation) -> Result<Value> {
        let fault = self
            .test_fault
            .as_ref()
            .filter(|p| p.exists())
            .map(|p| files::read(p, 128))
            .transpose()?
            .map(|raw| String::from_utf8_lossy(&raw).trim().to_string());
        Ok(store::mutate(
            &mut store::open(&self.ledger, true)?,
            m,
            fault.as_deref(),
        )?)
    }
    pub fn handle(
        &mut self,
        method: &str,
        path: &str,
        token: &str,
        data: &Value,
        query: &str,
        peer: &str,
    ) -> Result<Value> {
        if crate::cluster::config::read(&self.root)?
            .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
        {
            return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
        }
        if path.starts_with("/v1/cluster/") {
            return crate::cluster::api::handle(self, method, path, token, data, peer);
        }
        if method == "POST" && path == "/v1/login" {
            fields(data, &["username", "password"], &[])?;
            return self.auth.login(&data["username"], &data["password"], peer);
        }
        if method == "POST" && ["/v1/device/enroll", "/v1/device/session"].contains(&path) {
            let devices = self
                .devices
                .as_ref()
                .ok_or_else(|| Error::new(409, "DEVICE_PROTOCOL_CONFLICT"))?;
            return if path.ends_with("/enroll") {
                devices.enroll(&self.auth, data)
            } else {
                devices.session(&self.auth, data)
            };
        }
        let a = self
            .auth
            .authenticate(token)
            .or_else(|e| match &self.devices {
                Some(d) => d.authenticate(&self.auth, token),
                None => Err(e),
            })?;
        if let Some(d) = &self.devices {
            match (method, path) {
                ("POST", "/v1/device-grants") => return d.issue(&self.auth, &a, data),
                ("GET", "/v1/devices") => return d.listing(&a),
                _ if method == "POST" && path.starts_with("/v1/devices/") => {
                    fields(data, &[], &[])?;
                    return d.revoke(&a, &path[12..]);
                }
                _ => (),
            }
        }
        if method == "POST" && data.get("request_id").is_some() {
            let key = text(&data["request_id"], 36, true)?;
            store::id(key)?;
            let output = path == "/v1/outputs" || path.starts_with("/v1/outputs/");
            if output {
                if store::open(&self.ledger, false)?.query_row(
                    "SELECT EXISTS(SELECT 1 FROM requests WHERE request_id=?)",
                    [key],
                    |r| r.get::<_, bool>(0),
                )? {
                    return fail(409, "REVISION_OR_PRICE_CONFLICT");
                }
            } else if self
                .outputs
                .as_ref()
                .map(|o| o.has_request(key))
                .transpose()?
                .unwrap_or(false)
            {
                return fail(409, "REVISION_OR_PRICE_CONFLICT");
            }
        }
        if method == "GET" && path == "/v1/capabilities" {
            return Ok(
                json!({"device_auth":self.devices.as_ref().map(|_|crate::devices::FORMAT),"protocol":"777-service-v1","output_format":"777-output-v1","query_format":"777-query-v1","rule_version":RULE_VERSION,"numeric_profile":NUMERIC_PROFILE,"cents_encoding":"decimal-string","pricing_mode_version":"final-unit-v1"}),
            );
        }
        if path == "/v1/outputs" || path.starts_with("/v1/outputs/") {
            let o = self
                .outputs
                .as_ref()
                .ok_or_else(|| Error::new(503, "OUTPUTS_NOT_INITIALIZED"))?;
            if path == "/v1/outputs" && method == "GET" {
                let mut offset = 0u32;
                let mut seen = false;
                for (k, v) in form_urlencoded::parse(query.as_bytes()) {
                    if k != "offset" || seen {
                        return fail(422, "INVALID_QUERY");
                    }
                    offset = v.parse().map_err(|_| Error::new(422, "INVALID_QUERY"))?;
                    seen = true;
                }
                return o.listing_page(&a, offset);
            }
            if path == "/v1/outputs/report" && method == "POST" {
                Auth::admin(&a)?;
                fields(data, &["request_id", "from", "to"], &[])?;
                let mut d = data.clone();
                d["kind"] = json!("excel_period");
                let key = text(&d["request_id"], 36, true)?;
                store::id(key)?;
                let mut fp = d.clone();
                fp["actor"] = json!(a.subject);
                fp["role"] = json!(a.role);
                if let Some(v) = o.receipt(&a, key, Some(&store::hash(store::encoded(&fp))))? {
                    return Ok(v);
                }
                let date_format = time::format_description::parse("[year]-[month]-[day]")
                    .map_err(|_| Error::new(422, "INVALID_OUTPUT_REQUEST"))?;
                let from = text(&d["from"], 10, true)?;
                let to = text(&d["to"], 10, true)?;
                for value in [from, to] {
                    if value.len() != 10 || time::Date::parse(value, &date_format).is_err() {
                        return fail(422, "INVALID_OUTPUT_REQUEST");
                    }
                }
                if from > to {
                    return fail(422, "INVALID_OUTPUT_REQUEST");
                }
                let c = store::open(&self.ledger, false)?;
                c.execute_batch("BEGIN")?;
                let mut st=c.prepare("SELECT order_id FROM orders WHERE date(created_at,'+8 hours')>=? AND date(created_at,'+8 hours')<=? ORDER BY created_at,order_id")?;
                let ids = st.query_map([from, to], |r| r.get::<_, String>(0))?;
                let revision = store::verify(&c)?["revision"].clone();
                return crate::report_exports::enqueue(
                    o,
                    &a,
                    &d,
                    &revision,
                    ids.map(|id| Self::order_on(&c, &a, &id?, false)),
                );
            }
            if path == "/v1/outputs" && method == "POST" {
                fields(
                    data,
                    &["request_id", "order_id", "expected_revision", "kind"],
                    &["format"],
                )?;
                let mut d = data.clone();
                if d.get("format").is_none() {
                    d["format"] = json!("777-output-v1")
                }
                if d["format"] != "777-output-v1" {
                    return fail(409, "OUTPUT_VERSION_CONFLICT");
                }
                store::id(text(&d["order_id"], 36, true)?)?;
                if number(&d["expected_revision"])? < 1 {
                    return fail(422, "INVALID_OUTPUT_REQUEST");
                }
                if d["kind"] == "excel_period" {
                    return fail(422, "INVALID_OUTPUT_REQUEST");
                }
                if d["kind"] == "excel_admin" {
                    Auth::admin(&a)?
                }
                let mut fp = d.clone();
                fp["actor"] = json!(a.subject);
                fp["role"] = json!(a.role);
                if let Some(v) = o.receipt(
                    &a,
                    text(&d["request_id"], 36, true)?,
                    Some(&store::hash(store::encoded(&fp))),
                )? {
                    return Ok(v);
                }
                let order = self.order(&a, text(&d["order_id"], 36, true)?)?;
                if order["revision"] != d["expected_revision"] {
                    return fail(409, "ORDER_REVISION_CHANGED");
                }
                return o.enqueue(&a, &d, order);
            }
            let parts = path
                .trim_start_matches("/v1/outputs/")
                .split('/')
                .collect::<Vec<_>>();
            match (method, parts.as_slice()) {
                ("GET", [id]) => return o.status(&a, id),
                ("GET", [id, "content"]) => return o.content(&a, id),
                ("GET", [id, "location"]) => return o.location(&a, id),
                ("POST", [id, "retry"]) => {
                    fields(data, &["request_id"], &[])?;
                    return o.retry(&a, id, text(&data["request_id"], 36, true)?);
                }
                _ => return fail(404, "NOT_FOUND"),
            }
        }
        match (method, path) {
            ("POST", "/v1/logout") => {
                fields(data, &[], &[])?;
                if let Some(d) = &self.devices {
                    d.logout(token)?;
                }
                self.auth.logout(token)
            }
            ("GET", "/v1/me") => {
                Ok(json!({"subject":a.subject,"role":a.role,"protocol":"777-service-v1"}))
            }
            ("GET", "/v1/prices") => protocol::catalog(
                store::active_prices(&store::open(&self.ledger, false)?)?,
                &a,
            ),
            ("POST", "/v1/prices") => {
                Auth::admin(&a)?;
                fields(
                    data,
                    &["request_id", "prices", "expected_price_version_id"],
                    &[],
                )?;
                let expected = if data["expected_price_version_id"].is_null() {
                    None
                } else {
                    Some(text(&data["expected_price_version_id"], 256, false)?.into())
                };
                self.mutate(Mutation::PublishPrices {
                    request_id: text(&data["request_id"], 36, true)?.into(),
                    actor: a,
                    prices: protocol::prices(&data["prices"])?,
                    expected_price_version_id: expected,
                })
            }
            ("POST", "/v1/calculate") => {
                fields(data, &["snapshot"], &[])?;
                let q = protocol::quote(&data["snapshot"])?;
                let c = store::open(&self.ledger, false)?;
                c.execute_batch("BEGIN")?;
                let p = store::active_prices(&c)?;
                if q.price_version_id != p.price_version_id {
                    return fail(409, "PRICE_VERSION_CHANGED");
                }
                Ok(protocol::calculated(calculate(&q, &p), &a))
            }
            ("POST", "/v1/orders") => {
                fields(data, &["request_id", "snapshot", "details"], &[])?;
                let v = self.mutate(Mutation::SubmitOrder {
                    request_id: text(&data["request_id"], 36, true)?.into(),
                    actor: a.clone(),
                    snapshot: protocol::quote(&data["snapshot"])?,
                    details: protocol::details(&data["details"])?,
                })?;
                Ok(protocol::financial(v, &a))
            }
            ("POST", "/v1/customer-orders") => {
                crate::customers::listing(&store::open(&self.ledger, false)?, &a, data)
            }
            ("POST", "/v1/order-preview") | ("POST", "/v1/order-save") => {
                let saving = path == "/v1/order-save";
                fields(
                    data,
                    &["snapshot", "order_id", "expected_revision", "sources"],
                    if saving {
                        &["request_id", "details", "customer"]
                    } else {
                        &[]
                    },
                )?;
                if !data["order_id"].is_null() && !data["order_id"].is_string() {
                    return fail(422, "INVALID_BUSINESS_INPUT");
                }
                let oid = data["order_id"].as_str().map(str::to_string);
                if let Some(oid) = &oid {
                    store::id(oid)?;
                }
                let expected = if data["expected_revision"].is_null() {
                    None
                } else {
                    Some(number(&data["expected_revision"])?)
                };
                let sources: Vec<Option<String>> = serde_json::from_value(data["sources"].clone())
                    .map_err(|_| Error::new(422, "INVALID_BUSINESS_INPUT"))?;
                let snapshot = protocol::quote(&data["snapshot"])?;
                if saving {
                    let v = self.mutate(Mutation::SaveOrder {
                        request_id: text(&data["request_id"], 36, true)?.into(),
                        actor: a.clone(),
                        order_id: oid,
                        expected_revision: expected,
                        snapshot,
                        details: protocol::details(&data["details"])?,
                        sources,
                        customer: data["customer"].clone(),
                    })?;
                    Ok(protocol::financial(v, &a))
                } else {
                    let c = store::open(&self.ledger, false)?;
                    c.execute_batch("BEGIN")?;
                    let (result, _) = quote_ledger::editing::preview(
                        &c,
                        &a,
                        oid.as_deref(),
                        expected,
                        &snapshot,
                        &sources,
                    )?;
                    Ok(protocol::calculated(result, &a))
                }
            }
            ("GET", "/v1/analytics") => self.queries.analytics(&self.ledger, &a, query),
            ("GET", "/v1/orders") => self.queries.listing(&self.ledger, &a, query),
            ("POST", "/v1/notes") => {
                fields(
                    data,
                    &["request_id", "order_id", "body", "expected_revision"],
                    &[],
                )?;
                let v = self.mutate(Mutation::AppendNote {
                    request_id: text(&data["request_id"], 36, true)?.into(),
                    actor: a.clone(),
                    order_id: text(&data["order_id"], 36, true)?.into(),
                    body: text(&data["body"], 4096, false)?.into(),
                    expected_revision: number(&data["expected_revision"])?,
                })?;
                Ok(protocol::financial(v, &a))
            }
            ("POST", "/v1/state") => {
                Auth::admin(&a)?;
                fields(
                    data,
                    &[
                        "request_id",
                        "order_id",
                        "state",
                        "reason",
                        "expected_revision",
                    ],
                    &[],
                )?;
                let v = self.mutate(Mutation::SetState {
                    request_id: text(&data["request_id"], 36, true)?.into(),
                    actor: a.clone(),
                    order_id: text(&data["order_id"], 36, true)?.into(),
                    state: text(&data["state"], 16, true)?.into(),
                    reason: text(&data["reason"], 4096, false)?.into(),
                    expected_revision: number(&data["expected_revision"])?,
                })?;
                Ok(protocol::financial(v, &a))
            }
            ("GET", "/v1/settings") => self.auth.preferences(),
            ("POST", "/v1/settings") => self.auth.save_preferences(&a, data),
            ("GET", "/v1/accounts") => self.auth.accounts(&a),
            ("POST", "/v1/accounts") => self.auth.create_account(&a, data),
            ("GET", "/v1/backup") => {
                Auth::admin(&a)?;
                let status=backup::status(self).unwrap_or_else(|_|json!({"status":"unavailable","last_success":self.auth.backup_health().ok().map(|h|h["last_success"].clone())}));
                let mut v = json!({"target":self.config["backup_dir"],"plan":{"daily_hour":crate::daily_backup::config(self)?["daily_hour"],"utc_offset_minutes":480,"kind":"daily","automatic_retention":false},"service_health":self.auth.backup_health()?});
                v.as_object_mut()
                    .unwrap()
                    .extend(status.as_object().unwrap().clone());
                Ok(v)
            }
            ("POST", "/v1/backup") => {
                Auth::admin(&a)?;
                fields(data, &["kind"], &[])?;
                backup::create(self, text(&data["kind"], 32, true)?)
            }
            ("POST", "/v1/backup-plan") => {
                Auth::admin(&a)?;
                fail(403, "BACKUP_PLAN_DEVELOPER_ONLY")
            }
            _ => {
                if method == "GET" && path.starts_with("/v1/orders/") {
                    let pieces: Vec<_> =
                        path.trim_start_matches("/v1/orders/").split('/').collect();
                    if let [id, "changes", rev] = pieces.as_slice() {
                        store::id(id)?;
                        let revision: i64 = rev
                            .parse()
                            .ok()
                            .filter(|r| *r > 0 && *r < i64::MAX)
                            .ok_or_else(|| Error::new(422, "INVALID_QUERY"))?;
                        let c = store::open(&self.ledger, false)?;
                        c.execute_batch("BEGIN")?;
                        return crate::order_changes::read(&c, &a, id, revision);
                    }
                    return self.order(&a, &path[11..]);
                }
                if method == "POST" && path.starts_with("/v1/accounts/") {
                    return self.auth.update_account(&a, &path[13..], data);
                }
                if method == "GET" && path.starts_with("/v1/requests/") {
                    let key = &path[13..];
                    let mut v = store::query_request(&store::open(&self.ledger, false)?, key, &a)
                        .map_err(|e| {
                        if e.code == "FORBIDDEN" {
                            Error::new(404, "NOT_FOUND")
                        } else {
                            e.into()
                        }
                    })?;
                    if v.is_null() {
                        v = self
                            .outputs
                            .as_ref()
                            .map(|o| o.receipt(&a, key, None))
                            .transpose()?
                            .flatten()
                            .unwrap_or(Value::Null)
                    }
                    return Ok(json!({"result":if v.is_null(){v}else{protocol::financial(v,&a)}}));
                }
                fail(404, "NOT_FOUND")
            }
        }
    }
}
