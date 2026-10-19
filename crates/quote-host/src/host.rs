use crate::{
    auth::{self, Auth},
    backup, fail, files,
    outputs::Outputs,
    protocol::{self, text},
    service::Service,
    Error, Result,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use quote_ledger::{
    integrity,
    store::{self, hash, uid},
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
pub fn certificate_sha(path: &Path) -> Result<String> {
    let raw = files::read(path, 65536)?;
    let s =
        std::str::from_utf8(&raw).map_err(|_| Error::new(422, "CERTIFICATE_IDENTITY_CONFLICT"))?;
    if s.matches("-----BEGIN CERTIFICATE-----").count() != 1
        || s.matches("-----END CERTIFICATE-----").count() != 1
    {
        return fail(422, "CERTIFICATE_IDENTITY_CONFLICT");
    }
    let pem = s
        .split("-----BEGIN CERTIFICATE-----")
        .nth(1)
        .unwrap()
        .split("-----END CERTIFICATE-----")
        .next()
        .unwrap();
    let encoded = pem
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect::<String>();
    let der = STANDARD
        .decode(encoded)
        .map_err(|_| Error::new(422, "CERTIFICATE_IDENTITY_CONFLICT"))?;
    Ok(hash(der))
}
pub fn validate_resources(private: &Path, config: &Value) -> Result<()> {
    if config
        .get("ledger_backend")
        .is_some_and(|v| v != "python" && v != "rust")
        || config
            .get("service_backend")
            .is_some_and(|v| v != "python" && v != "rust")
    {
        return fail(422, "HOST_BACKEND_INVALID");
    }
    for (field, file, notice) in [
        (
            "rust_worker_sha256",
            "rust-ledger-worker.exe",
            "rust-notices.txt",
        ),
        (
            "rust_host_sha256",
            "rust-service-host.exe",
            "rust-host-notices.txt",
        ),
    ] {
        if let Some(sha) = config.get(field) {
            let expected = text(sha, 64, true)?;
            if expected.len() != 64
                || !expected
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                || files::sha(&private.join(file))? != expected
            {
                return fail(503, "HOST_RESOURCE_IDENTITY_CONFLICT");
            }
            files::local(&private.join(notice), true)?;
        }
    }
    if config.get("ledger_backend") == Some(&json!("rust"))
        && config.get("rust_worker_sha256").is_none()
        || config.get("service_backend") == Some(&json!("rust"))
            && (config.get("rust_host_sha256").is_none()
                || config.get("ledger_backend") != Some(&json!("rust")))
    {
        return fail(422, "HOST_BACKEND_INVALID");
    }
    Ok(())
}
#[derive(Clone)]
pub struct Init {
    pub root: PathBuf,
    pub backups: PathBuf,
    pub hosts: Vec<String>,
    pub bind: String,
    pub port: u16,
    pub user: String,
    pub secret: String,
    pub worker: PathBuf,
    pub notices: PathBuf,
    pub auxiliary: bool,
}
pub fn initialize(v: Init) -> Result<Value> {
    if !cfg!(windows) && !v.auxiliary {
        return fail(400, "WINDOWS_HOST_REQUIRED");
    }
    if cfg!(windows) && v.auxiliary {
        return fail(400, "WINDOWS_SECURITY_CANNOT_BE_DISABLED");
    }
    auth::username(&json!(v.user))?;
    auth::password(&json!(v.secret))?;
    if v.port == 0 || v.bind.parse::<std::net::IpAddr>().is_err() || v.hosts.is_empty() {
        return fail(422, "HOST_CONFIG_INVALID");
    }
    let mut params = rcgen::CertificateParams::new(v.hosts.clone())
        .map_err(|_| Error::new(422, "CERTIFICATE_HOSTS_REQUIRED"))?;
    params.distinguished_name = rcgen::DistinguishedName::new();
    params
        .distinguished_name
        .push(rcgen::DnType::CommonName, "777 service");
    params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Constrained(0));
    params.key_usages = vec![
        rcgen::KeyUsagePurpose::DigitalSignature,
        rcgen::KeyUsagePurpose::KeyCertSign,
    ];
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
    params.not_before = time::OffsetDateTime::now_utc() - time::Duration::minutes(5);
    params.not_after = time::OffsetDateTime::now_utc() + time::Duration::days(365);
    params.use_authority_key_identifier_extension = true;
    let key = rcgen::KeyPair::generate().map_err(|_| Error::new(503, "TLS_IDENTITY_FAILED"))?;
    let cert = params
        .self_signed(&key)
        .map_err(|_| Error::new(503, "TLS_IDENTITY_FAILED"))?;
    files::local(&v.worker, true)?;
    files::local(&v.notices, true)?;
    let worker_sha = files::sha(&v.worker)?;
    let executable = std::env::current_exe()?;
    let host_sha = files::sha(&executable)?;
    if v.root.exists() || v.root == v.backups {
        return fail(409, "HOST_REQUIRES_NEW_DIRECTORIES");
    }
    files::new_dir(&v.root)?;
    let private = v.root.join("private");
    files::new_dir(&private)?;
    let security = files::protect(&private, v.auxiliary)?;
    let backup_destination = crate::backup::destination(&v.backups)?;
    let inventory = store::create(&private.join("ledger.sqlite3"))?;
    Auth::create(&private.join("auth.sqlite3"), &v.user, &v.secret)?;
    Outputs::create(
        &private.join("outputs.sqlite3"),
        inventory["ledger_id"].as_str().unwrap(),
    )?;
    files::copy(&v.worker, &private.join("rust-ledger-worker.exe"))?;
    if probe_worker(&v.worker, &private.join("ledger.sqlite3"), v.auxiliary)? != inventory {
        return fail(503, "WORKER_RESOURCE_INCOMPATIBLE");
    }
    files::copy(&v.notices, &private.join("rust-notices.txt"))?;
    files::copy(&executable, &private.join("rust-service-host.exe"))?;
    files::copy(&v.notices, &private.join("rust-host-notices.txt"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for n in ["rust-ledger-worker.exe", "rust-service-host.exe"] {
            fs::set_permissions(private.join(n), fs::Permissions::from_mode(0o700))?;
        }
    }
    files::new_file(&private.join("tls-key.pem"), key.serialize_pem().as_bytes())?;
    files::new_file(&private.join("tls-cert.pem"), cert.pem().as_bytes())?;
    let storeid = &backup_destination["store_id"];
    let fingerprint = hash(cert.der());
    let config = json!({"schema":"777-host-v1","ledger_id":inventory["ledger_id"],"backup_store_id":storeid,"backup_dir":v.backups.to_string_lossy(),"bind":v.bind,"port":v.port,"certificate_sha256":fingerprint,"private_security":security,"maintenance":false,"ledger_backend":"rust","rust_worker_sha256":worker_sha,"service_backend":"rust","rust_host_sha256":host_sha});
    files::replace_json(&private.join("service.json"), &config)?;
    files::copy(
        &private.join("tls-cert.pem"),
        &v.root.join("service-cert.pem"),
    )?;
    let host = if v.hosts[0].contains(':') {
        format!("[{}]", v.hosts[0])
    } else {
        v.hosts[0].clone()
    };
    files::replace_json(
        &v.root.join("client-template.json"),
        &json!({"schema":"777-service-client-v1","url":format!("https://{host}:{}",v.port),"certificate":v.root.join("service-cert.pem").to_string_lossy(),"certificate_sha256":fingerprint,"username":""}),
    )?;
    Service::load(&v.root, v.auxiliary, false)?;
    Ok(config)
}
pub struct Selection<'a> {
    pub root: &'a Path,
    pub user: &'a str,
    pub password: &'a str,
    pub backend: &'a str,
    pub worker: Option<&'a Path>,
    pub notices: Option<&'a Path>,
    pub upgrade: bool,
    pub auxiliary: bool,
}
pub fn select(options: Selection<'_>) -> Result<Value> {
    let Selection {
        root,
        user,
        password,
        backend,
        worker,
        notices,
        upgrade,
        auxiliary,
    } = options;
    if !["python", "rust"].contains(&backend) {
        return fail(422, "HOST_BACKEND_INVALID");
    }
    let _owner = files::Owner::acquire(root)?;
    let mut s = Service::load(root, auxiliary, true)?;
    let login = s
        .auth
        .login(&json!(user), &json!(password), "offline-host-selection")?;
    let token = login["token"].as_str().unwrap();
    let a = s.auth.authenticate(token)?;
    let result = (|| -> Result<Value> {
        Auth::admin(&a)?;
        if backend == "python" && s.devices.is_some() {
            return fail(409, "DEVICE_AUTH_REQUIRES_NATIVE_HOST");
        }
        let executable = std::env::current_exe()?;
        let sha = files::sha(&executable)?;
        if s.config.get("service_backend").unwrap_or(&json!("python")) == backend
            && (backend == "python" || s.config["rust_host_sha256"] == sha)
        {
            return Ok(s.config.clone());
        }
        let before = integrity::inventory(&store::open(&s.ledger, false)?)?;
        let private = root.join("private");
        let mut config = s.config.clone();
        let mut replacements = vec![];
        if backend == "rust" {
            let notice = notices.ok_or_else(|| Error::new(422, "NOTICES_REQUIRED"))?;
            files::local(notice, true)?;
            if s.config
                .get("rust_host_sha256")
                .is_some_and(|old| old != &json!(sha))
                && !upgrade
            {
                return fail(409, "EXPLICIT_RESOURCE_UPGRADE_REQUIRED");
            }
            for (field, file, src, noticefile) in [
                (
                    "rust_host_sha256",
                    "rust-service-host.exe",
                    Some(executable.as_path()),
                    "rust-host-notices.txt",
                ),
                (
                    "rust_worker_sha256",
                    "rust-ledger-worker.exe",
                    worker,
                    "rust-notices.txt",
                ),
            ] {
                if field == "rust_worker_sha256" && config.get(field).is_some() && src.is_none() {
                    continue;
                }
                let src = src.ok_or_else(|| Error::new(422, "WORKER_REQUIRED"))?;
                let newsha = files::sha(src)?;
                if field == "rust_worker_sha256"
                    && probe_worker(src, &s.ledger, auxiliary)? != before
                {
                    return fail(503, "WORKER_RESOURCE_INCOMPATIBLE");
                }
                let dest = private.join(file);
                if config.get(field) == Some(&json!(newsha)) {
                    continue;
                }
                if config.get(field).is_none()
                    && (dest.exists() || private.join(noticefile).exists())
                {
                    return fail(409, "UNOWNED_RUNTIME_RESOURCE_EXISTS");
                }
                if config.get(field).is_some_and(|old| old != &json!(newsha)) && !upgrade {
                    return fail(409, "EXPLICIT_RESOURCE_UPGRADE_REQUIRED");
                }
                replacements.push((dest, files::read(src, 512 * 1024 * 1024)?));
                replacements.push((
                    private.join(noticefile),
                    files::read(notice, 16 * 1024 * 1024)?,
                ));
                config[field] = json!(newsha);
            }
            config["ledger_backend"] = json!("rust");
        }
        config["service_backend"] = json!(backend);
        let old = replacements
            .iter()
            .map(|(p, _)| {
                Ok((
                    p.clone(),
                    if p.exists() {
                        Some(files::read(p, 512 * 1024 * 1024)?)
                    } else {
                        None
                    },
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        let publish = (|| -> Result<Value> {
            for (p, raw) in &replacements {
                let temp = p.with_extension(format!("{}.partial", uid()?));
                files::new_file(&temp, raw)?;
                fs::rename(temp, p)?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    if p.extension().is_some_and(|x| x == "exe") {
                        fs::set_permissions(p, fs::Permissions::from_mode(0o700))?;
                    }
                }
            }
            validate_resources(&private, &config)?;
            if integrity::inventory(&store::open(&s.ledger, false)?)? != before {
                return fail(503, "HOST_SELECTION_LEDGER_CHANGED");
            }
            files::replace_json(&private.join("service.json"), &config)?;
            let observed = Service::load(root, auxiliary, true)?;
            if observed.config != config {
                return fail(503, "HOST_SELECTION_UNVERIFIED");
            }
            Ok(config)
        })();
        if publish.is_err() {
            for (p, raw) in old {
                if let Some(raw) = raw {
                    let temp = p.with_extension(format!("{}.rollback", uid()?));
                    files::new_file(&temp, &raw)?;
                    fs::rename(temp, p)?;
                } else if p.exists() {
                    fs::remove_file(p)?;
                }
            }
            files::replace_json(&private.join("service.json"), &s.config)?;
        }
        publish
    })();
    let _ = s.auth.logout(token);
    result
}
#[derive(Clone)]
struct State {
    service: Arc<Mutex<Service>>,
    capacity: Arc<tokio::sync::Semaphore>,
    peer: Option<Arc<crate::cluster::transport::Peer>>,
    dirty: Arc<AtomicBool>,
}
async fn handler(
    axum::extract::State(state): axum::extract::State<State>,
    axum::extract::ConnectInfo(peer): axum::extract::ConnectInfo<std::net::SocketAddr>,
    req: axum::extract::Request,
) -> axum::response::Response {
    use axum::{
        body::{to_bytes, Body},
        http::{Response, StatusCode},
    };
    let started = std::time::Instant::now();
    let peer_execution_id = req
        .headers()
        .get("x-777-execution-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| quote_diagnostics::valid_id(v))
        .map(str::to_owned);
    let method_log = if req.method() == "POST" {
        "POST"
    } else {
        "GET/other"
    };
    let route = req.uri().path().split('/').nth(2).unwrap_or("");
    let route_log = match route {
        "auth" | "devices" | "prices" | "orders" | "backups" | "settings" | "outputs"
        | "calculate" | "health" | "order-preview" | "order-save" | "customer-orders"
        | "cluster" | "automatic" => route.to_owned(),
        _ => "other".into(),
    };
    let result = (|| -> Result<(String, String, String, String, String)> {
        let headers = req.headers();
        for name in [
            "authorization",
            "content-type",
            "content-length",
            "x-777-package-authorization",
            "x-777-execution-id",
        ] {
            if headers.get_all(name).iter().count() > 1 {
                return fail(400, "DUPLICATE_HEADERS");
            }
        }
        if headers.contains_key("origin") {
            return fail(403, "BROWSER_ORIGIN_NOT_ALLOWED");
        }
        if req.uri().scheme_str().is_some_and(|s| s != "https") {
            return fail(400, "HTTPS_REQUIRED");
        }
        let token = headers
            .get("authorization")
            .map(|h| h.as_bytes())
            .unwrap_or(&[]);
        if token.len() > 256 {
            return fail(401, "UNAUTHENTICATED");
        }
        let token = if let Some(t) = token.strip_prefix(b"Bearer ") {
            std::str::from_utf8(t)
                .map_err(|_| Error::new(401, "UNAUTHENTICATED"))?
                .to_string()
        } else {
            String::new()
        };
        if req.method() == "POST"
            && headers
                .get("content-type")
                .and_then(|h| h.to_str().ok())
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                != "application/json"
        {
            return fail(415, "JSON_REQUIRED");
        }
        if req.uri().path().starts_with("/v1/automatic/") && req.uri().query().is_some() {
            return fail(422, "INVALID_QUERY");
        }
        let package_token = headers
            .get("x-777-package-authorization")
            .map(|v| v.to_str().map_err(|_| Error::new(401, "UNAUTHENTICATED")))
            .transpose()?
            .unwrap_or("");
        if package_token.len() > 64
            || !package_token.is_empty() && !req.uri().path().starts_with("/v1/automatic/")
        {
            return fail(400, "INVALID_HEADERS");
        }
        let package_token = package_token
            .strip_prefix("Bearer ")
            .unwrap_or("")
            .to_owned();
        Ok((
            req.method().as_str().into(),
            req.uri().path().into(),
            req.uri().query().unwrap_or("").into(),
            token,
            package_token,
        ))
    })();
    let result = match result {
        Err(e) => Err(e),
        Ok((method, path, query, token, package_token)) => {
            match state.capacity.clone().try_acquire_owned() {
                Err(_) => fail(429, "SERVICE_CAPACITY"),
                Ok(permit) => {
                    let data = if method == "POST" {
                        match tokio::time::timeout(
                            Duration::from_secs(10),
                            to_bytes(
                                req.into_body(),
                                if path.starts_with("/v1/automatic/") {
                                    65536
                                } else if path.starts_with("/v1/cluster/") {
                                    2 * protocol::BODY_LIMIT
                                } else {
                                    protocol::BODY_LIMIT
                                },
                            ),
                        )
                        .await
                        {
                            Ok(Ok(raw)) => protocol::decode(
                                &raw,
                                if path.starts_with("/v1/automatic/") {
                                    65536
                                } else if path.starts_with("/v1/cluster/") {
                                    2 * protocol::BODY_LIMIT
                                } else {
                                    protocol::BODY_LIMIT
                                },
                            ),
                            Ok(Err(_)) => fail(413, "BODY_TOO_LARGE"),
                            Err(_) => fail(408, "BODY_TIMEOUT"),
                        }
                    } else {
                        Ok(Value::Null)
                    };
                    match data {
                        Err(e) => Err(e),
                        Ok(data) if state.peer.is_some() => {
                            let _permit = permit;
                            if path.starts_with("/v1/cluster/") {
                                fail(409, "CLUSTER_REPLICA_CANNOT_WRITE")
                            } else {
                                state
                                    .peer
                                    .as_ref()
                                    .unwrap()
                                    .forward(&method, &path, &query, &token, &data)
                                    .await
                            }
                        }
                        Ok(data) => {
                            let dirty = state.dirty.clone();
                            tokio::task::spawn_blocking(move || {
                                let _permit = permit;
                                let mut service = state
                                    .service
                                    .lock()
                                    .map_err(|_| Error::new(503, "SERVICE_UNAVAILABLE"))?;
                                let changes =
                                    crate::cluster::runtime::changes(&method, &path, &data);
                                let result = if path.starts_with("/v1/automatic/") {
                                    crate::automatic::api::handle(
                                        &service,
                                        &method,
                                        &path,
                                        &token,
                                        &package_token,
                                        &data,
                                        &peer.ip().to_string(),
                                    )
                                } else {
                                    service.handle(
                                        &method,
                                        &path,
                                        &token,
                                        &data,
                                        &query,
                                        &peer.ip().to_string(),
                                    )
                                };
                                if changes {
                                    dirty.store(true, Ordering::SeqCst);
                                }
                                result
                            })
                            .await
                            .unwrap_or_else(|_| fail(500, "SERVICE_FAILED"))
                        }
                    }
                }
            }
        }
    };
    let (status, value) = match result {
        Ok(v) => (200, v),
        Err(e) => (e.status, json!({"error":e.code})),
    };
    let record = if ["order-preview", "order-save"].contains(&route_log.as_str()) {
        quote_diagnostics::event_each
    } else {
        quote_diagnostics::event
    };
    if route_log != "cluster" {
        record(
            "http.finish",
            json!({"method":method_log,"route":route_log,"peer_execution_id":peer_execution_id,"status":status,"error":value.get("error")}),
        );
    }
    if started.elapsed() >= Duration::from_secs(5) {
        quote_diagnostics::event(
            "http.slow",
            json!({"route":route_log,"seconds":started.elapsed().as_secs()}),
        );
    }
    let body = store::encoded(&value);
    Response::builder()
        .status(StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header("content-type", "application/json; charset=utf-8")
        .header("cache-control", "no-store")
        .header("content-length", body.len())
        .body(Body::from(body))
        .unwrap()
}
pub async fn serve(mut service: Service, test_stdin: bool) -> Result<()> {
    if service.config["service_backend"] != "rust" || service.config["ledger_backend"] != "rust" {
        return fail(409, "RUST_HOST_NOT_SELECTED");
    }
    if files::sha(&std::env::current_exe()?)? != service.config["rust_host_sha256"] {
        return fail(503, "HOST_RESOURCE_IDENTITY_CONFLICT");
    }
    let _owner = files::Owner::acquire(&service.root)?;
    // Re-read after owner acquisition to close the offline-selection/start race.
    let mut loaded = Service::load(&service.root, service.auxiliary, false)?;
    loaded.font = service.font.take();
    loaded.test_fault = service.test_fault.take();
    if loaded.config != service.config {
        return fail(409, "HOST_CONFIGURATION_CHANGED");
    }
    let cluster = crate::cluster::config::read(&loaded.root)?;
    let replica = cluster
        .as_ref()
        .is_some_and(|c| c.role == crate::cluster::config::Role::Replica);
    if !replica {
        if let Some(o) = &loaded.outputs {
            o.recover()?;
        }
    } else {
        let publication = crate::cluster::snapshot::current(&loaded.root)?
            .ok_or_else(|| Error::new(503, "CLUSTER_INITIAL_SYNC_REQUIRED"))?;
        let manifest = crate::cluster::snapshot::read(&loaded.root, &publication)?;
        crate::cluster::snapshot::validate_data(
            &crate::cluster::snapshot::folder(&loaded.root, &publication)?,
            &manifest,
        )?;
    }
    let upstream = if let Some(c) = cluster.as_ref().filter(|_| replica) {
        Some(Arc::new(crate::cluster::transport::Peer::new(
            c,
            crate::cluster::config::secret(&loaded.root, loaded.auxiliary)?,
        )?))
    } else {
        None
    };
    let root = loaded.root.clone();
    let private = loaded.root.join("private");
    rustls::crypto::ring::default_provider()
        .install_default()
        .ok();
    let tls = axum_server::tls_rustls::RustlsConfig::from_pem_file(
        private.join("tls-cert.pem"),
        private.join("tls-key.pem"),
    )
    .await?;
    let mut config = (*tls.get_inner()).clone();
    config.alpn_protocols = vec![b"http/1.1".to_vec()];
    let tls = axum_server::tls_rustls::RustlsConfig::from_config(Arc::new(config));
    let address = std::net::SocketAddr::new(
        loaded.config["bind"]
            .as_str()
            .unwrap()
            .parse()
            .map_err(|_| Error::new(422, "HOST_CONFIG_INVALID"))?,
        crate::number(&loaded.config["port"])? as u16,
    );
    let listener = std::net::TcpListener::bind(address)?;
    listener.set_nonblocking(true)?;
    let bound = listener.local_addr()?;
    let service = Arc::new(Mutex::new(loaded));
    let dirty = Arc::new(AtomicBool::new(true));
    let state = State {
        service: service.clone(),
        capacity: Arc::new(tokio::sync::Semaphore::new(8)),
        peer: upstream.clone(),
        dirty: dirty.clone(),
    };
    let app = axum::Router::new().fallback(handler).with_state(state);
    let handle = axum_server::Handle::new();
    let stop = Arc::new(AtomicBool::new(false));
    if test_stdin {
        let h = handle.clone();
        let stop = stop.clone();
        std::thread::spawn(move || {
            let mut line = String::new();
            let _ = std::io::stdin().read_line(&mut line);
            stop.store(true, Ordering::SeqCst);
            h.graceful_shutdown(Some(Duration::from_secs(45)));
        });
    }
    let h = handle.clone();
    let stop_signal = stop.clone();
    tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            stop_signal.store(true, Ordering::SeqCst);
            h.graceful_shutdown(Some(Duration::from_secs(45)));
        }
    });
    let pairing = match crate::automatic::pairing::start(service.clone(), stop.clone()).await {
        Ok(value) => value,
        Err(error) => {
            quote_diagnostics::event(
                "automatic.binding.start_failed",
                json!({"error":error.code}),
            );
            None
        }
    };
    let output_service = service.clone();
    let output_stop = stop.clone();
    let output_dirty = dirty.clone();
    let worker = tokio::task::spawn_blocking(move || {
        while !output_stop.load(Ordering::SeqCst) {
            if replica {
                std::thread::sleep(Duration::from_millis(100));
                continue;
            }
            let work = output_service
                .lock()
                .ok()
                .and_then(|s| s.prepare_output().ok())
                .flatten();
            if let Some(work) = work {
                output_dirty.store(true, Ordering::SeqCst);
                let outcome = work.execute();
                if let Ok(s) = output_service.lock() {
                    if let Some(o) = &s.outputs {
                        let _ = o.finish(&work, outcome);
                        output_dirty.store(true, Ordering::SeqCst);
                    }
                }
            } else {
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    });
    let schedule_service = service.clone();
    let schedule_stop = stop.clone();
    let schedule_dirty = dirty.clone();
    let schedule = tokio::task::spawn_blocking(move || {
        let mut checked = std::time::Instant::now();
        while !schedule_stop.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(100));
            if checked.elapsed() >= crate::daily_backup::CHECK_INTERVAL {
                checked = std::time::Instant::now();
                if replica {
                    continue;
                }
                let check = schedule_service
                    .lock()
                    .ok()
                    .map(|s| crate::daily_backup::check(&s));
                if check.is_some_and(|check| check.is_ok_and(|check| !check.ready())) {
                    continue;
                }
                if let Ok(s) = schedule_service.lock() {
                    let outcome = backup::due(&s);
                    if !matches!(outcome, Ok(None)) {
                        schedule_dirty.store(true, Ordering::SeqCst);
                    }
                    if let Err(e) = outcome {
                        quote_diagnostics::event("backup.schedule.error", json!({"error":e.code}));
                        let _ = s
                            .auth
                            .record_backup(None, Some(&format!("DAILY_BACKUP_FAILED:{}", e.code)));
                    }
                }
            }
        }
    });
    let synchronization = if let Some(upstream) = upstream {
        let stopped = stop.clone();
        Some(tokio::spawn(crate::cluster::replica::run(
            upstream, root, stopped,
        )))
    } else if let Some(cluster) = cluster {
        let stopped = stop.clone();
        let source = service.clone();
        Some(tokio::task::spawn_blocking(move || {
            crate::cluster::runtime::source(source, cluster, root, stopped, dirty)
        }))
    } else {
        None
    };
    let server = axum_server::from_tcp_rustls(listener, tls)?
        .http1_only()
        .handle(handle);
    let acceptor = crate::transport::Capacity {
        inner: server.get_ref().clone(),
        slots: Arc::new(tokio::sync::Semaphore::new(16)),
    };
    let mut server = server.acceptor(acceptor);
    server
        .http_builder()
        .http1()
        .timer(hyper_util::rt::TokioTimer::new())
        .max_buf_size(32768)
        .header_read_timeout(Duration::from_secs(10))
        .keep_alive(true);
    println!(
        "{}",
        json!({"status":"ready","port":bound.port(),"protocol":"777-service-v1","host_backend":"rust"})
    );
    let result = server
        .serve(app.into_make_service_with_connect_info::<std::net::SocketAddr>())
        .await;
    stop.store(true, Ordering::SeqCst);
    worker
        .await
        .map_err(|_| Error::new(503, "OUTPUT_WORKER_FAILED"))?;
    schedule
        .await
        .map_err(|_| Error::new(503, "BACKUP_WORKER_FAILED"))?;
    if let Some(synchronization) = synchronization {
        synchronization
            .await
            .map_err(|_| Error::new(503, "CLUSTER_WORKER_FAILED"))?;
    }
    if let Some(pairing) = pairing {
        let _ = pairing.await;
    }
    result?;
    Ok(())
}
/// Compatibility resource probe occurs only during offline initialization or
/// explicit resource selection. The running Rust service never spawns workers.
pub fn probe_worker(worker: &Path, ledger: &Path, auxiliary: bool) -> Result<Value> {
    use std::io::{Read, Write};
    let mut command = std::process::Command::new(worker);
    command.arg(ledger);
    if auxiliary {
        command.arg("--auxiliary");
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|_| Error::new(503, "WORKER_RESOURCE_INCOMPATIBLE"))?;
    let mut input = child.stdin.take().unwrap();
    input.write_all(br#"{"op":"inventory"}"#)?;
    drop(input);
    let output = child.stdout.take().unwrap();
    let errors = child.stderr.take().unwrap();
    let out = std::thread::spawn(move || {
        let mut raw = vec![];
        output.take(65537).read_to_end(&mut raw).map(|_| raw)
    });
    let err = std::thread::spawn(move || {
        let mut raw = vec![];
        errors.take(65537).read_to_end(&mut raw)
    });
    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            let _ = out.join();
            let _ = err.join();
            return fail(503, "WORKER_RESOURCE_INCOMPATIBLE");
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    let raw = out
        .join()
        .map_err(|_| Error::new(503, "WORKER_RESOURCE_INCOMPATIBLE"))??;
    let _ = err.join();
    if !status.success() || raw.len() > 65536 {
        return fail(503, "WORKER_RESOURCE_INCOMPATIBLE");
    }
    let v = protocol::decode(&raw, 65536)?;
    if v["ok"] != true {
        return fail(503, "WORKER_RESOURCE_INCOMPATIBLE");
    }
    Ok(v["result"].clone())
}
