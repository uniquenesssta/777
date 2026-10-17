use crate::{
    journal::Store,
    tls,
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
    store: Store,
    session: Option<Session>,
    calculation: Option<Calculation>,
    auto_expires: u64,
}
impl Desktop {
    pub fn new(root: PathBuf, auxiliary: bool) -> Result<Self> {
        Ok(Self {
            store: Store::new(root, auxiliary)?,
            session: None,
            calculation: None,
            auto_expires: 0,
        })
    }
    pub fn has_pending(&self) -> Result<bool> {
        Ok(self.store.read::<Pending>("pending.bin")?.is_some())
    }
    pub async fn directory_context(&mut self, target: &str) -> Result<String> {
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
            self.admin()?;
            let state = crate::developer::call(json!({"op":"status"})).await?;
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
        let bytes = body
            .map(serde_json::to_vec)
            .transpose()
            .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?;
        if bytes.as_ref().is_some_and(|b| b.len() > REQUEST_LIMIT) {
            return Err(DesktopError::new(413, "BODY_TOO_LARGE"));
        }
        let mut req = s
            .http
            .request(
                reqwest::Method::from_bytes(method.as_bytes())
                    .map_err(|_| DesktopError::new(422, "INVALID_METHOD"))?,
                format!("{}{}", s.connection.url.trim_end_matches('/'), path),
            )
            .header("Accept", "application/json");
        if !s.token.is_empty() {
            req = req.bearer_auth(&s.token);
        }
        if let Some(bytes) = bytes {
            req = req.header("Content-Type", "application/json").body(bytes);
        }
        let mut response = req.send().await.map_err(|e| {
            #[cfg(feature = "verification")]
            eprintln!("verification TLS failure: {e:?}");
            let _ = e;
            DesktopError::new(0, "SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED")
        })?;
        let status = response.status().as_u16();
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| DesktopError::new(0, "SERVICE_RESPONSE_INCOMPLETE"))?
        {
            if bytes.len() + chunk.len() > 8 * REQUEST_LIMIT {
                return Err(DesktopError::new(413, "SERVICE_RESPONSE_TOO_LARGE"));
            }
            bytes.extend_from_slice(&chunk);
        }
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|_| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?;
        if status != 200 {
            if status == 401 {
                if let Some(s) = &mut self.session {
                    s.token.clear();
                }
                self.calculation = None;
            }
            return Err(DesktopError::new(
                status,
                value["error"]
                    .as_str()
                    .unwrap_or("SERVICE_RESPONSE_INVALID"),
            ));
        }
        Ok(value)
    }
    async fn mutate(&mut self, path: &str, mut body: Value) -> Result<Value> {
        if self.store.read::<Pending>("pending.bin")?.is_some() {
            return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
        }
        let s = self.session()?;
        if s.token.is_empty() {
            return Err(DesktopError::new(401, "UNAUTHENTICATED"));
        }
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
        if crate::startup::formal()
            && !matches!(
                action,
                Action::Bootstrap {}
                    | Action::Connection {}
                    | Action::Connect { .. }
                    | Action::Disconnect {}
            )
            && self.auto_expires <= clock() + 30
        {
            self.bootstrap().await?;
        }
        let mut v = self.execute_inner(action).await?;
        display(&mut v);
        Ok(v)
    }
    async fn bootstrap(&mut self) -> Result<Value> {
        use crate::startup::{self, Bootstrap, Credential};
        let kind = startup::delivery();
        if !startup::formal() {
            #[cfg(all(
                debug_assertions,
                not(any(feature = "manager", feature = "sales", feature = "verification"))
            ))]
            if crate::developer::available() {
                let config = crate::developer::bootstrap().await?;
                let session = Box::pin(
                    self.execute_inner(Action::Connect {
                        connection: serde_json::from_value(config["connection"].clone())
                            .map_err(|_| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?,
                        username: config["username"]
                            .as_str()
                            .ok_or_else(|| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?
                            .into(),
                        password: config["password"]
                            .as_str()
                            .ok_or_else(|| DesktopError::new(502, "DEVELOPER_CONFIG_INVALID"))?
                            .into(),
                    }),
                )
                .await?;
                return Ok(json!({"delivery":kind,"session":session,"automatic":true}));
            }
            if let Some(config) = self.store.bootstrap::<Bootstrap>()? {
                config.validate(kind)?;
                let session = Box::pin(self.execute_inner(Action::Connect {
                    connection: config.connection,
                    username: config.username.unwrap(),
                    password: config.password.unwrap(),
                }))
                .await?;
                return Ok(json!({"delivery":kind,"session":session,"automatic":true}));
            }
            return Ok(json!({"delivery":kind,"session":null,"automatic":false}));
        }
        let mut saved = self.store.read::<Credential>("device.bin")?;
        // A newly delivered operator grant replaces only the device credential.
        // Pending financial requests are retained and must still match the original actor/service.
        if let (Some(old), Some(next)) = (&saved, self.store.bootstrap::<Bootstrap>()?) {
            next.validate(kind)?;
            if serde_json::to_value(&old.config).ok() != serde_json::to_value(&next).ok() {
                self.store.clear("device.bin")?;
                saved = None;
                self.session = None;
                self.auto_expires = 0;
            }
        }
        let credential = match saved {
            Some(c) => c,
            None => {
                let config = self
                    .store
                    .bootstrap::<Bootstrap>()?
                    .ok_or_else(|| DesktopError::new(409, "DEPLOYMENT_NOT_CONFIGURED"))?;
                config.validate(kind)?;
                use base64::Engine;
                let mut b = [0u8; 32];
                getrandom::getrandom(&mut b)
                    .map_err(|_| DesktopError::new(503, "RANDOM_UNAVAILABLE"))?;
                let c = Credential {
                    config,
                    device_id: new_id()?,
                    secret: base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b),
                    profile: self.store.profile(),
                };
                self.store.write("device.bin", &c)?;
                c
            }
        };
        credential.config.validate(kind)?;
        if credential.profile != self.store.profile() {
            return Err(DesktopError::new(403, "DEVICE_PROFILE_MISMATCH"));
        }
        self.calculation = None;
        self.session = Some(Session {
            http: tls::build(&credential.config.connection)?,
            connection: credential.config.connection.clone(),
            token: String::new(),
            subject: String::new(),
            role: String::new(),
        });
        let enrolled=self.request("POST","/v1/device/enroll",Some(&json!({"ticket":credential.config.ticket,"device_id":credential.device_id,"device_secret":credential.secret,"delivery":kind}))).await?;
        if enrolled["protocol"] != "777-device-auth-v1" {
            self.session = None;
            return Err(DesktopError::new(409, "DEVICE_PROTOCOL_CONFLICT"));
        }
        let v=self.request("POST","/v1/device/session",Some(&json!({"device_id":credential.device_id,"device_secret":credential.secret,"delivery":kind}))).await?;
        let expected = if kind == "manager" { "admin" } else { "sales" };
        if v["protocol"] != "777-device-auth-v1"
            || v["role"] != expected
            || v["subject"] != enrolled["subject"]
        {
            self.session = None;
            return Err(DesktopError::new(403, "DELIVERY_ROLE_MISMATCH"));
        }
        let token = v["token"]
            .as_str()
            .filter(|s| s.len() == 43)
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
            .to_owned();
        let s = self.session.as_mut().unwrap();
        s.token = token;
        s.subject = v["subject"]
            .as_str()
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
            .to_owned();
        s.role = expected.into();
        self.auto_expires = v["expires"]
            .as_u64()
            .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?;
        let caps = self.request("GET", "/v1/capabilities", None).await?;
        if caps["device_auth"] != "777-device-auth-v1" || caps["cents_encoding"] != "decimal-string"
        {
            self.session = None;
            return Err(DesktopError::new(409, "DEVICE_PROTOCOL_CONFLICT"));
        }
        self.store.clear("bootstrap.json")?;
        Ok(
            json!({"delivery":kind,"automatic":true,"session":{"subject":v["subject"],"role":expected,"username":v["username"],"pending":self.has_pending()?,"pricing_mode_version":caps["pricing_mode_version"]}}),
        )
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
                self.admin()?;
                if request.protects_close() && self.has_pending()? {
                    return Err(DesktopError::new(409, "PENDING_REQUEST_REQUIRES_QUERY"));
                }
                let switches = request.switches_data();
                let mut data = serde_json::to_value(&request)
                    .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?;
                if matches!(request, crate::developer::DeveloperAction::Package { .. }) {
                    // The connection comes from the authenticated native session, not an arbitrary frontend URL.
                    data["connection"] = serde_json::to_value(&self.session()?.connection)
                        .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?;
                }
                let result = crate::developer::call(data).await?;
                if switches {
                    self.session = None;
                    self.calculation = None;
                    self.auto_expires = 0;
                }
                Ok(result)
            }
            Action::Bootstrap {} => self.bootstrap().await,
            Action::Connection {} => Ok(
                json!({"delivery":crate::startup::delivery(),"automatic":crate::startup::formal() || self.store.bootstrap::<crate::startup::Bootstrap>()?.is_some(),"connection":if crate::startup::formal(){None}else{self.store.read::<Connection>("connection.bin")?},"pending":self.has_pending()?}),
            ),
            Action::Connect {
                connection,
                username,
                password,
            } => {
                if crate::startup::formal() {
                    return Err(DesktopError::new(403, "MANUAL_LOGIN_DISABLED"));
                }
                if username.is_empty() || username.chars().count() > 64 || password.len() > 4096 {
                    return Err(DesktopError::new(422, "INVALID_LOGIN"));
                }
                let http = tls::build(&connection)?;
                self.session = None;
                self.calculation = None;
                self.session = Some(Session {
                    http,
                    connection: connection.clone(),
                    token: String::new(),
                    subject: String::new(),
                    role: String::new(),
                });
                let v = self
                    .request(
                        "POST",
                        "/v1/login",
                        Some(&json!({"username":username,"password":password})),
                    )
                    .await?;
                let token = v["token"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
                    .to_string();
                let subject = v["subject"]
                    .as_str()
                    .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
                    .to_string();
                let role = v["role"]
                    .as_str()
                    .filter(|s| ["admin", "sales"].contains(s))
                    .ok_or_else(|| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?
                    .to_string();
                self.session.as_mut().unwrap().token = token;
                self.session.as_mut().unwrap().subject = subject.clone();
                self.session.as_mut().unwrap().role = role.clone();
                let capabilities = self.request("GET", "/v1/capabilities", None).await?;
                if capabilities["protocol"] != "777-service-v1"
                    || capabilities["cents_encoding"] != "decimal-string"
                {
                    self.session = None;
                    return Err(DesktopError::new(409, "PROTOCOL_VERSION_CONFLICT"));
                }
                self.store.clear("connection.bin")?;
                self.store.write("connection.bin", &connection)?;
                Ok(
                    json!({"subject":subject,"role":role,"username":username,"pending":self.has_pending()?,"pricing_mode_version":capabilities["pricing_mode_version"]}),
                )
            }
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
                self.calculation = None;
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
            Action::SaveOrder{snapshot,sources,order_id,expected_revision,draft_revision,details,customer} => {
                let expected=expected_revision.map(|s|revision(&s)).transpose()?;
                let mut context=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected});
                let c=self.calculation.as_ref().ok_or_else(||DesktopError::new(409,"CALCULATION_REQUIRED"))?;
                if c.snapshot!=context||c.revision!=draft_revision||c.result["status"]!="ok"{return Err(DesktopError::new(409,"CALCULATION_STALE"));}
                context["details"]=details;context["customer"]=customer;
                let result=self.mutate("/v1/order-save",context).await;
                self.calculation=None;result
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
                self.mutate(
                    "/v1/prices",
                    json!({"prices":prices,"expected_price_version_id":expected_price_version_id}),
                )
                .await
            }
            Action::Settings {} => self.request("GET", "/v1/settings", None).await,
            Action::SaveSettings {
                revision: rev,
                export_dir,
                image_dir,
            } => {
                self.admin()?;
                self.request("POST","/v1/settings",Some(&json!({"revision":revision(&rev)?,"export_dir":export_dir,"image_dir":image_dir}))).await
            }
            Action::Outputs {} => self.request("GET", "/v1/outputs", None).await,
            Action::OpenOutputFolder { job_id } => {
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
                self.mutate("/v1/outputs",json!({"order_id":order_id,"expected_revision":revision(&expected_revision)?,"kind":kind})).await
            }
            Action::RetryOutput { job_id } => {
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
                self.request("POST", "/v1/backup", Some(&json!({"kind":"maintenance"})))
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
        ] {
            let action =
                serde_json::from_value(json!({"action":"developer","request":request})).unwrap();
            assert_eq!(
                desktop.execute(action).await.unwrap_err().code,
                "PENDING_REQUEST_REQUIRES_QUERY"
            );
            assert_eq!(std::fs::read(root.join("pending.bin")).unwrap(), before);
        }
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
