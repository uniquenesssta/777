mod automatic;
mod connections;
mod credentials;
mod data_source;
mod enrollment;
#[cfg(test)]
mod future_contract;
mod offline;
mod preferences;
mod restricted_outputs;
mod retry;
mod transport;

use crate::{
    journal::Store,
    permissions, tls,
    types::{identifier, new_id, revision},
    Action, Connection, DesktopError, Result,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;
const REQUEST_LIMIT: usize = 1024 * 1024;
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Pending {
    path: String,
    body: Value,
    subject: String,
    url: String,
    pin: String,
}
#[derive(Clone)]
struct Session {
    http: reqwest::Client,
    connection: Connection,
    token: String,
    subject: String,
    role: String,
}
struct Calculation {
    snapshot: Value,
    revision: String,
    result: Value,
}
pub struct Desktop {
    runtime_id: String,
    store: Store,
    session: Option<Session>,
    calculation: Option<Calculation>,
    auto_expires: u64,
    package_session: Option<Session>,
    automatic_package: Option<quote_security::automatic::Package>,
    automatic_retry: retry::AutomaticRetry,
    local: crate::offline::Local,
    last_tcp: Option<bool>,
}
impl Desktop {
    pub fn new(root: PathBuf, auxiliary: bool) -> Result<Self> {
        let store = Store::new(root, auxiliary)?;
        let (path, auxiliary) = store.local_database()?;
        Ok(Self {
            runtime_id: new_id()?,
            store,
            session: None,
            calculation: None,
            auto_expires: 0,
            package_session: None,
            automatic_package: None,
            automatic_retry: retry::AutomaticRetry::default(),
            local: crate::offline::Local::open(path, auxiliary)?,
            last_tcp: None,
        })
    }
    pub fn has_pending(&self) -> Result<bool> {
        Ok(self.store.read::<Pending>("pending.bin")?.is_some())
    }
    pub async fn directory_context(&mut self, target: &str) -> Result<String> {
        permissions::authorize(
            &permissions::selected()?,
            &Action::PickDirectory {
                target: target.into(),
            },
        )?;
        if target == "public_connection" && !crate::startup::formal() {
            return Ok(String::new());
        }
        if target == "device_enrollment" && crate::startup::formal() {
            return Ok(String::new());
        }
        if target == "business_directory" {
            let value = self.execute(Action::BusinessDirectory {}).await?;
            return Ok(value["directory"].as_str().unwrap_or("").into());
        }
        #[cfg(all(
            debug_assertions,
            not(any(feature = "manager", feature = "sales", feature = "verification"))
        ))]
        if [
            "developer_root",
            "developer_backup",
            "developer_output",
            "developer_hidden",
            "developer_restore",
            "developer_recovery_file",
        ]
        .contains(&target)
        {
            connections::development()?;
            let state = crate::developer::call(
                json!({"op":if target == "developer_output" {"package_status"} else {"status"}}),
            )
            .await?;
            return Ok(match target {
                "developer_root" => state["root"].as_str(),
                "developer_backup" | "developer_recovery_file" => state["backup_dir"].as_str(),
                "developer_hidden" => state["daily"]["hidden_dir"].as_str(),
                "developer_restore" => state["root"].as_str(),
                _ => state["preferences"]["output"].as_str(),
            }
            .unwrap_or("")
            .to_string());
        }
        if !["export_dir", "image_dir"].contains(&target) {
            return Err(DesktopError::new(422, "INVALID_DIRECTORY_TARGET"));
        }
        let settings = self.execute(Action::Settings {}).await?;
        self.admin()?;
        Ok(settings[target].as_str().unwrap_or("").to_string())
    }
    fn session(&self) -> Result<&Session> {
        self.session
            .as_ref()
            .ok_or_else(|| DesktopError::new(401, "UNAUTHENTICATED"))
    }
    fn admin(&self) -> Result<()> {
        if self.session()?.role != "admin" {
            return Err(DesktopError::new(403, "ADMIN_REQUIRED"));
        }
        Ok(())
    }
    async fn request(&mut self, method: &str, path: &str, body: Option<&Value>) -> Result<Value> {
        let s = self.session()?;
        let mut result = transport::request(s, method, path, body).await;
        if !crate::startup::formal()
            && path != "/v1/logout"
            && result.as_ref().is_err_and(|e| e.status == 401)
            && self.renew_development().await.is_ok()
        {
            result = transport::request(self.session()?, method, path, body).await;
        }
        if result.as_ref().is_err_and(|e| e.status == 401) {
            if let Some(s) = &mut self.session {
                s.token.clear();
            }
            self.calculation = None;
        }
        result
    }
    async fn mutate(&mut self, path: &str, mut body: Value) -> Result<Value> {
        if self.store.read::<Pending>("pending.bin")?.is_some() {
            return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
        }
        if self.session()?.token.is_empty() {
            if crate::startup::formal() {
                return Err(DesktopError::new(401, "UNAUTHENTICATED"));
            }
            self.renew_development().await?;
        }
        let s = self.session()?;
        body["request_id"] = json!(new_id()?);
        if serde_json::to_vec(&body)
            .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?
            .len()
            > REQUEST_LIMIT
        {
            return Err(DesktopError::new(413, "BODY_TOO_LARGE"));
        }
        let p = Pending {
            path: path.into(),
            body,
            subject: s.subject.clone(),
            url: s.connection.url.clone(),
            pin: s.connection.certificate_sha256.clone(),
        };
        self.store.write("pending.bin", &p)?;
        self.send_pending(&p).await
    }
    async fn send_pending(&mut self, p: &Pending) -> Result<Value> {
        permissions::pending(&permissions::selected()?, &p.path, &p.body)?;
        if let Some(id) = p
            .path
            .strip_prefix("/v1/outputs/")
            .and_then(|v| v.strip_suffix("/retry"))
        {
            self.authorize_output(id).await?;
        }
        let s = self.session()?;
        if p.subject != s.subject
            || p.url != s.connection.url
            || p.pin != s.connection.certificate_sha256
        {
            return Err(DesktopError::new(403, "PENDING_IDENTITY_MISMATCH"));
        }
        match self.request("POST", &p.path, Some(&p.body)).await {
            Ok(v) => {
                self.store.clear("pending.bin")?;
                Ok(v)
            }
            Err(e) if e.status == 0 || e.status >= 500 || e.status == 202 || e.status == 401 => {
                Err(DesktopError::new(202, "COMMIT_UNKNOWN"))
            }
            Err(e) => {
                self.store.clear("pending.bin")?;
                Err(e)
            }
        }
    }
    pub async fn execute(&mut self, action: Action) -> Result<Value> {
        if matches!(action, Action::UiDiagnostic { .. }) {
            return self.execute_inner(action).await;
        }
        let operation = action.diagnostic_name();
        let record: fn(&str, Value) = if matches!(
            action,
            Action::Order { .. }
                | Action::OrderPreview { .. }
                | Action::SaveOrder { .. }
                | Action::Submit { .. }
                | Action::Note { .. }
                | Action::SetState { .. }
        ) {
            quote_diagnostics::event_each
        } else {
            quote_diagnostics::event
        };
        record("desktop.action.start", json!({"operation":operation}));
        let result = self.execute_logged(action).await;
        record(
            "desktop.action.finish",
            json!({"operation":operation,"error":result.as_ref().err().map(|e|&e.code)}),
        );
        result
    }
    async fn execute_logged(&mut self, action: Action) -> Result<Value> {
        let policy = permissions::selected()?;
        permissions::authorize(&policy, &action)?;
        if crate::startup::formal() && self.local.active()? {
            self.local_context()?;
            if let Some(mut v) = self.local_action(&action)? {
                display(&mut v);
                if !permissions::has(&policy, "finance") {
                    permissions::redact_financial(&mut v);
                }
                return Ok(v);
            }
        }
        if crate::startup::formal()
            && !matches!(
                action,
                Action::Bootstrap {}
                    | Action::Connection {}
                    | Action::Connect { .. }
                    | Action::Disconnect {}
                    | Action::ImportEnrollment { .. }
            )
            && self.auto_expires <= clock() + 30
        {
            if self.automatic_package.is_some() {
                self.bootstrap_automatic().await?;
            } else {
                self.bootstrap().await?;
            }
        }
        let mut v = self.execute_inner(action).await?;
        display(&mut v);
        if !permissions::has(&policy, "finance") {
            permissions::redact_financial(&mut v);
        }
        Ok(v)
    }
    async fn bootstrap(&mut self) -> Result<Value> {
        use crate::startup::{self, Bootstrap};
        let kind = startup::delivery();
        if !startup::formal() {
            if self.host_selected()? {
                let connection = self
                    .saved_connection()?
                    .ok_or_else(|| DesktopError::new(422, "INVALID_CONNECTION"))?;
                let session = self.connect_selected(connection, None, None).await?;
                return Ok(json!({"delivery":kind,"session":session,"automatic":true}));
            }
            #[cfg(all(
                debug_assertions,
                not(any(feature = "manager", feature = "sales", feature = "verification"))
            ))]
            if crate::developer::available() {
                let config = crate::developer::bootstrap().await?;
                let session = self
                    .connect(
                        serde_json::from_value(config["connection"].clone())
                            .map_err(|_| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?,
                        config["username"]
                            .as_str()
                            .ok_or_else(|| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?
                            .into(),
                        config["password"]
                            .as_str()
                            .ok_or_else(|| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?
                            .into(),
                        "local",
                    )
                    .await?;
                return Ok(json!({"delivery":kind,"session":session,"automatic":true}));
            }
            if let Some(config) = self.store.bootstrap::<Bootstrap>()? {
                config.validate(kind)?;
                let session = self
                    .connect(
                        config.connection,
                        config.username.unwrap(),
                        config.password.unwrap(),
                        "local",
                    )
                    .await?;
                return Ok(json!({"delivery":kind,"session":session,"automatic":true}));
            }
            return Ok(json!({"delivery":kind,"session":null,"automatic":false}));
        }
        self.bootstrap_formal().await
    }
    async fn execute_inner(&mut self, action: Action) -> Result<Value> {
        match action {
            Action::UiDiagnostic { event, order_id, revision: order_revision, draft_revision, lines, error_kind, source, line, column } => {
                if let Some(id) = &order_id { identifier(id)?; }
                for r in [order_revision.as_deref(), draft_revision.as_deref()].into_iter().flatten() {
                    if r.is_empty() || r.len() > 40 || !r.bytes().all(|b| b.is_ascii_digit()) {
                        return Err(DesktopError::new(422, "INVALID_REVISION"));
                    }
                }
                let record = if matches!(event, crate::UiEvent::FrontendError) { quote_diagnostics::event } else { quote_diagnostics::event_each };
                record("ui.event", json!({"event":event,"order_id":order_id,"revision":order_revision,"draft_revision":draft_revision,"lines":lines,"error_kind":error_kind,"source":source,"line":line,"column":column}));
                Ok(Value::Null)
            }
            #[cfg(all(
                debug_assertions,
                not(any(feature = "manager", feature = "sales", feature = "verification"))
            ))]
            Action::Developer { request } => {
                connections::development()?;
                if request.protects_close() && self.has_pending()? {
                    return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
                }
                let switches = request.switches_data();
                let data = serde_json::to_value(&request)
                    .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?;
                if let crate::developer::DeveloperAction::Package { ref delivery, ref permissions } = request {
                    crate::permissions::validate(delivery, permissions)?;
                }
                let result = crate::developer::call(data).await?;
                if switches {
                    self.remember_source("local", serde_json::from_value(result["connection"].clone()).map_err(|_|DesktopError::new(502,"DEVELOPER_CONFIG_INVALID"))?)?;
                    self.session = None;
                    self.calculation = None;
                    self.auto_expires = 0;
                }
                Ok(result)
            }
            Action::Bootstrap {} => self.bootstrap().await,
            Action::Connection {} => Ok(
                json!({"runtime_id":self.runtime_id,"delivery":crate::startup::delivery(),"developer_tools":crate::startup::developer_tools(),"automatic":crate::startup::formal() || self.store.bootstrap::<crate::startup::Bootstrap>()?.is_some(),"connection":if crate::startup::formal(){None}else{self.saved_connection()?},"pending":self.has_pending()?,"permissions":permissions::selected()?}),
            ),
            Action::ImportConnection { path } => {
                connections::development()?;
                Ok(json!({"connection": crate::connection_file::public(&path)?}))
            }
            Action::ImportEnrollment { path } => self.import_enrollment(&path).await,
            Action::BusinessDirectory {} => self.business_directory(None).await,
            Action::SaveBusinessDirectory { directory } => self.business_directory(Some(directory)).await,
            Action::PackageTarget {} => self.package_target(),
            Action::UseCurrentPackageTarget {} => self.use_current_package_target().await,
            Action::VerifyPackageTarget { connection, username, password } => self.verify_package_target(connection, username, password).await,
            Action::Connect { connection, username, password } => self.connect_selected(connection, username, password).await,
            Action::Disconnect {} => {
                let result = self.request("POST", "/v1/logout", Some(&json!({}))).await;
                self.session = None;
                self.calculation = None;
                result
            }
            Action::PickDirectory { .. } => {
                self.admin()?;
                Err(DesktopError::new(422, "DIRECTORY_DIALOG_REQUIRES_WINDOW"))
            }
            Action::Analytics { period, from, to } => {
                self.admin()?;
                if !["day", "week", "month", "year"].contains(&period.as_str())
                    || ![10, 19, 23].contains(&from.len())
                    || ![10, 19, 23].contains(&to.len())
                {
                    return Err(DesktopError::new(422, "INVALID_ANALYTICS_QUERY"));
                }
                let mut url = reqwest::Url::parse("https://local/v1/analytics").unwrap();
                url.query_pairs_mut()
                    .append_pair("period", &period)
                    .append_pair("from", &from)
                    .append_pair("to", &to);
                self.request(
                    "GET",
                    &format!("{}?{}", url.path(), url.query().unwrap()),
                    None,
                )
                .await
                .map_err(|e| {
                    if e.status == 404 {
                        DesktopError::new(409, "ANALYTICS_NOT_SUPPORTED")
                    } else {
                        e
                    }
                })
            }
            Action::Prices {} => self.request("GET", "/v1/prices", None).await,
            Action::PricePreview { cost, k } => {
                self.admin()?;
                let price = quote_core::models::PriceItem {
                    product_id: json!("preview"),
                    sale: json!(""),
                    cost: json!(cost),
                    k: json!(k),
                    single: json!(true),
                    discount_eligible: None,
                    pricing_mode: Some(quote_core::models::PricingMode::CostPlus),
                };
                let sale = quote_core::pricing::unit_sale(&price)
                    .map_err(|_| DesktopError::new(422, "INVALID_PRICE_INPUT"))?;
                Ok(json!({"sale":sale.text()}))
            }
            Action::Calculate {
                snapshot,
                draft_revision,
            } => {
                revision(&draft_revision)?;
                self.calculation = None;
                let result = self
                    .request("POST", "/v1/calculate", Some(&json!({"snapshot":snapshot})))
                    .await?;
                self.calculation = Some(Calculation {
                    snapshot,
                    revision: draft_revision.clone(),
                    result: result.clone(),
                });
                Ok(json!({"draft_revision":draft_revision,"result":result}))
            }
            Action::Submit {
                snapshot,
                details,
                draft_revision,
                ..
            } => {
                let c = self
                    .calculation
                    .as_ref()
                    .ok_or_else(|| DesktopError::new(409, "CALCULATION_REQUIRED"))?;
                if c.snapshot != snapshot
                    || c.revision != draft_revision
                    || c.result["status"] != "ok"
                {
                    return Err(DesktopError::new(409, "CALCULATION_STALE"));
                }
                let result = self
                    .mutate("/v1/orders", json!({"snapshot":snapshot,"details":details}))
                    .await;
                if result.is_ok() { self.calculation = None; }
                result
            }
            Action::CustomerOrders{query,offset,group_id,order_offset} => self.request("POST","/v1/customer-orders",Some(&json!({"query":query,"offset":offset,"group_id":group_id,"order_offset":order_offset.unwrap_or(0)}))).await,
            Action::OrderPreview{snapshot,sources,order_id,expected_revision,draft_revision} => {
                revision(&draft_revision)?;
                self.calculation=None;
                let expected=expected_revision.map(|s|revision(&s)).transpose()?;
                let context=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected});
                let result=self.request("POST","/v1/order-preview",Some(&context)).await?;
                self.calculation=Some(Calculation{snapshot:context,revision:draft_revision.clone(),result:result.clone()});
                Ok(json!({"draft_revision":draft_revision,"result":result}))
            }
            Action::SaveOrder{snapshot,sources,order_id,expected_revision,draft_revision,details,customer,..} => {
                let expected=expected_revision.map(|s|revision(&s)).transpose()?;
                let mut context=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected});
                let c=self.calculation.as_ref().ok_or_else(||DesktopError::new(409,"CALCULATION_REQUIRED"))?;
                if c.snapshot!=context||c.revision!=draft_revision||c.result["status"]!="ok"{return Err(DesktopError::new(409,"CALCULATION_STALE"));}
                context["details"]=details;context["customer"]=customer;
                let result=self.mutate("/v1/order-save",context).await;
                if result.is_ok() { self.calculation=None; } result
            }
            Action::LocalReceipt{operation_id}=>{
                identifier(&operation_id)?;
                if self.local.active()?{self.local.saved_receipt(&operation_id)}else{Ok(json!({"result":null,"submitted":null}))}
            }
            Action::Orders {
                q,
                state,
                offset,
                view,
            } => {
                if q.chars().count() > 256
                    || !["", "active", "void"].contains(&state.as_str())
                    || offset > 1000000
                {
                    return Err(DesktopError::new(422, "INVALID_QUERY"));
                }
                let mut url = reqwest::Url::parse("https://local/v1/orders").unwrap();
                {
                    let mut p = url.query_pairs_mut();
                    p.append_pair("q", &q)
                        .append_pair("limit", "20")
                        .append_pair("offset", &offset.to_string());
                    if !state.is_empty() {
                        p.append_pair("state", &state);
                    }
                    if !view.is_empty() {
                        p.append_pair("view", &view);
                    }
                }
                self.request(
                    "GET",
                    &format!("/v1/orders?{}", url.query().unwrap_or("")),
                    None,
                )
                .await
            }
            Action::OrderChanges {order_id,revision:rev} => {
                let result=self.request("GET",&format!("/v1/orders/{}/changes/{}",identifier(&order_id)?,revision(&rev)?),None).await?;
                if self.local.active()?{self.local.put(&format!("diff:{order_id}:{rev}"),&result)?;}
                Ok(result)
            }
            Action::Order { order_id } => {
                self.request(
                    "GET",
                    &format!("/v1/orders/{}", identifier(&order_id)?),
                    None,
                )
                .await
            }
            Action::Note {
                order_id,
                expected_revision,
                body,
            } => {
                identifier(&order_id)?;
                let rev = revision(&expected_revision)?;
                self.mutate(
                    "/v1/notes",
                    json!({"order_id":order_id,"expected_revision":rev,"body":body}),
                )
                .await
            }
            Action::SetState {
                order_id,
                expected_revision,
                state,
                reason,
            } => {
                self.admin()?;
                identifier(&order_id)?;
                let rev = revision(&expected_revision)?;
                self.mutate("/v1/state",json!({"order_id":order_id,"expected_revision":rev,"state":state,"reason":reason})).await
            }
            Action::PublishPrices {
                prices,
                expected_price_version_id,
            } => {
                self.admin()?;
                self.calculation = None;
                let result=self.mutate(
                    "/v1/prices",
                    json!({"prices":prices,"expected_price_version_id":expected_price_version_id}),
                ).await?;
                if self.local.active()?{self.local.put("prices_changed",&json!(true))?;self.local.put("ready_checked",&json!(0))?;}
                Ok(result)
            }
            Action::Settings {} => self.request("GET", "/v1/settings", None).await,
            Action::SaveSettings {
                revision: rev,
                export_dir,
                image_dir,
            } => {
                self.admin()?;
                let result=self.request("POST","/v1/settings",Some(&json!({"revision":revision(&rev)?,"export_dir":export_dir,"image_dir":image_dir}))).await?;
                if self.local.active()?{self.local.put("settings",&result)?;}
                Ok(result)
            }
            Action::Outputs { offset } => self.visible_outputs(offset).await,
            Action::OpenOutputFolder { job_id } => {
                self.authorize_output(&job_id).await?;
                let location = self
                    .request(
                        "GET",
                        &format!("/v1/outputs/{}/location", identifier(&job_id)?),
                        None,
                    )
                    .await?;
                let path = location["output_path"]
                    .as_str()
                    .ok_or_else(|| DesktopError::new(409, "OUTPUT_LOCATION_UNAVAILABLE"))?
                    .to_owned();
                let url = self.session()?.connection.url.clone();
                tokio::task::spawn_blocking(move || crate::output_folder::open(&path, &url))
                    .await
                    .map_err(|_| DesktopError::new(503, "OUTPUT_FOLDER_UNAVAILABLE"))??;
                Ok(json!({"opened":true}))
            }
            Action::CreateReport{from,to}=>{
                self.admin()?;
                self.mutate("/v1/outputs/report",json!({"from":from,"to":to})).await
            },
            Action::CreateOutput {
                order_id,
                expected_revision,
                kind,
            } => {
                identifier(&order_id)?;
                if !["excel_quote", "excel_admin", "quote_png"].contains(&kind.as_str()) {
                    return Err(DesktopError::new(422, "INVALID_OUTPUT_KIND"));
                }
                if kind == "excel_admin" {
                    self.admin()?;
                }
                let expected=if self.local.active()?{self.local.output_revision(&order_id,&expected_revision)?}else{expected_revision};
                self.mutate("/v1/outputs",json!({"order_id":order_id,"expected_revision":revision(&expected)?,"kind":kind})).await
            }
            Action::DeleteOutput { job_id } => {
                self.authorize_output(&job_id).await?;
                self.mutate(&format!("/v1/outputs/{}/delete", identifier(&job_id)?), json!({})).await
            }
            Action::RetryOutput { job_id } => {
                self.authorize_output(&job_id).await?;
                self.mutate(
                    &format!("/v1/outputs/{}/retry", identifier(&job_id)?),
                    json!({}),
                )
                .await
            }
            Action::Recover { retry } => {
                let Some(p) = self.store.read::<Pending>("pending.bin")? else {
                    return Ok(json!({"pending":false,"result":null}));
                };
                let s = self.session()?;
                if p.subject != s.subject
                    || p.url != s.connection.url
                    || p.pin != s.connection.certificate_sha256
                {
                    return Err(DesktopError::new(403, "PENDING_IDENTITY_MISMATCH"));
                }
                let receipt = self
                    .request(
                        "GET",
                        &format!(
                            "/v1/requests/{}",
                            identifier(p.body["request_id"].as_str().unwrap_or(""))?
                        ),
                        None,
                    )
                    .await?;
                if !receipt["result"].is_null() {
                    self.store.clear("pending.bin")?;
                    return Ok(
                        json!({"pending":false,"result":receipt["result"],"path":p.path,"submitted":if ["/v1/orders","/v1/order-save"].contains(&p.path.as_str()) {p.body.clone()} else {Value::Null}}),
                    );
                }
                if retry {
                    return Ok(
                        json!({"pending":false,"result":self.send_pending(&p).await?,"path":p.path,"submitted":if ["/v1/orders","/v1/order-save"].contains(&p.path.as_str()) {p.body.clone()} else {Value::Null}}),
                    );
                }
                Ok(json!({"pending":true,"result":null,"request_id":p.body["request_id"]}))
            }
            Action::BackupStatus {} => {
                self.admin()?;
                self.request("GET", "/v1/backup", None).await
            }
            Action::Backup {} => {
                self.admin()?;
                self.request("POST", "/v1/backup", Some(&json!({"kind":"daily"})))
                    .await
            }
        }
    }
}
fn clock() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}
fn display(v: &mut Value) {
    match v {
        Value::Array(a) => a.iter_mut().for_each(display),
        Value::Object(o) => {
            for (k, x) in o.iter_mut() {
                if ["revision", "ledger_revision", "order_revision"].contains(&k.as_str())
                    && x.is_number()
                {
                    *x = json!(x.to_string());
                } else {
                    display(x);
                }
            }
            if let (Some(income), Some(cost)) = (
                o.get("income_cents")
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<i64>().ok()),
                o.get("cost_cents")
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<i64>().ok()),
            ) {
                if let Ok(a) = quote_core::models::Amounts::new(income, cost, false) {
                    o.insert("financial_display".into(), a.display());
                }
            }
        }
        _ => {}
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn runtime_identity_changes_on_reopen_but_pending_receipt_survives() {
        let root = std::env::temp_dir().join(format!("777-runtime-{}", new_id().unwrap()));
        let mut desktop = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        desktop
            .store
            .write(
                "pending.bin",
                &Pending {
                    path: "/v1/order-save".into(),
                    body: json!({"request_id":"preserved"}),
                    subject: "test".into(),
                    url: "https://127.0.0.1:8477".into(),
                    pin: "a".repeat(64),
                },
            )
            .unwrap();
        let first = desktop.execute(Action::Connection {}).await.unwrap();
        assert_eq!(
            desktop.execute(Action::Connection {}).await.unwrap()["runtime_id"],
            first["runtime_id"]
        );
        drop(desktop);
        let mut reopened = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        let next = reopened.execute(Action::Connection {}).await.unwrap();
        assert_ne!(first["runtime_id"], next["runtime_id"]);
        assert_eq!(next["pending"], true);
        assert_eq!(
            reopened
                .store
                .read::<Pending>("pending.bin")
                .unwrap()
                .unwrap()
                .body["request_id"],
            "preserved"
        );
        drop(reopened);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[cfg(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    ))]
    #[tokio::test]
    async fn developer_switch_and_backup_reject_pending_before_launcher_call() {
        let root =
            std::env::temp_dir().join(format!("777-developer-pending-{}", new_id().unwrap()));
        let mut desktop = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
        let _ = rustls::crypto::ring::default_provider().install_default();
        desktop.session = Some(Session {
            http: reqwest::Client::new(),
            connection: Connection {
                url: "https://127.0.0.1:1".into(),
                certificate_pem: String::new(),
                certificate_sha256: "a".repeat(64),
            },
            token: "isolated".into(),
            subject: "original".into(),
            role: "admin".into(),
        });
        desktop
            .store
            .write(
                "pending.bin",
                &Pending {
                    path: "/v1/orders".into(),
                    body: json!({"request_id":"original"}),
                    subject: "original".into(),
                    url: "https://127.0.0.1:1".into(),
                    pin: "a".repeat(64),
                },
            )
            .unwrap();
        let before = std::fs::read(root.join("pending.bin")).unwrap();
        for request in [
            json!({"op":"select","root":"ignored","initialize":false,"backup_dir":""}),
            json!({"op":"backup_directory","directory":"ignored"}),
            json!({"op":"daily_backup","directory":"ignored","hidden":"ignored","hour":23}),
            json!({"op":"restore_data","package":"ignored","target":"ignored"}),
            json!({"op":"import_directory","root":"ignored","target":"ignored","username":"admin","password":"unused"}),
        ] {
            let action =
                serde_json::from_value(json!({"action":"developer","request":request})).unwrap();
            assert_eq!(
                desktop.execute(action).await.unwrap_err().code,
                "PENDING_REQUEST_REQUIRES_QUERY"
            );
            assert_eq!(std::fs::read(root.join("pending.bin")).unwrap(), before);
        }
        drop(desktop);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn developer_wire_excludes_private_bootstrap_and_arbitrary_commands() {
        for op in ["bootstrap", "shell", "read_file"] {
            assert!(serde_json::from_value::<Action>(
                json!({"action":"developer","request":{"op":op}})
            )
            .is_err());
        }
        #[cfg(any(
            not(debug_assertions),
            feature = "manager",
            feature = "sales",
            feature = "verification"
        ))]
        assert!(serde_json::from_value::<Action>(
            json!({"action":"developer","request":{"op":"status"}})
        )
        .is_err());
    }
    #[test]
    fn wire_rejects_arbitrary_paths_actor_and_unknown_commands() {
        for raw in [
            r#"{"action":"request","path":"/v1/accounts"}"#,
            r#"{"action":"orders","q":"","state":"","offset":0,"view":"","actor":"admin"}"#,
            r#"{"action":"backup","role":"admin"}"#,
        ] {
            assert!(serde_json::from_str::<Action>(raw).is_err());
        }
    }
    #[test]
    fn display_preserves_exact_large_cents_and_safe_revision_strings() {
        let mut v = json!({"income_cents":"9007199254740993","cost_cents":"1","revision":9007199254740993u64});
        display(&mut v);
        assert_eq!(v["income_cents"], "9007199254740993");
        assert_eq!(v["revision"], "9007199254740993");
        assert_eq!(v["financial_display"]["income"], "90071992547409.93");
    }
}
