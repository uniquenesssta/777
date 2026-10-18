//! Temporary, pinned HTTPS binding surface. No business/issuer APIs are routed here.
use super::*;
use crate::service::Service;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
#[derive(Clone)]
struct State {
    service: Arc<Mutex<Service>>,
    peer: std::net::IpAddr,
    upgrade: String,
    expires: i64,
    slots: Arc<tokio::sync::Semaphore>,
}
async fn handle(
    axum::extract::State(state): axum::extract::State<State>,
    axum::extract::ConnectInfo(peer): axum::extract::ConnectInfo<std::net::SocketAddr>,
    req: axum::extract::Request,
) -> axum::response::Response {
    let result = async {
        if peer.ip() != state.peer || auth::now() >= state.expires {
            return Err(denied());
        }
        let _slot = state
            .slots
            .try_acquire()
            .map_err(|_| Error::new(429, "AUTOMATIC_RATE_LIMIT"))?;
        if req.method() != "POST"
            || req.uri().path() != "/v1/automatic/binding/pair"
            || req.uri().query().is_some()
            || req.headers().contains_key("origin")
        {
            return fail(404, "NOT_FOUND");
        }
        for name in ["authorization", "content-type", "content-length"] {
            if req.headers().get_all(name).iter().count() > 1 {
                return fail(400, "DUPLICATE_HEADERS");
            }
        }
        if req
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .is_none_or(|s| s.split(';').next() != Some("application/json"))
        {
            return fail(415, "JSON_REQUIRED");
        }
        let token = req
            .headers()
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.strip_prefix("Bearer "))
            .ok_or_else(denied)?
            .to_string();
        digest(&token)?;
        let raw = tokio::time::timeout(
            Duration::from_secs(10),
            axum::body::to_bytes(req.into_body(), 65536),
        )
        .await
        .map_err(|_| Error::new(408, "BODY_TIMEOUT"))?
        .map_err(|_| Error::new(413, "BODY_TOO_LARGE"))?;
        let data = crate::protocol::decode(&raw, 65536)?;
        if data["upgrade_id"] != state.upgrade {
            return Err(denied());
        }
        super::api::rate(&peer.ip().to_string(), &token)?;
        let s = state.service.lock().map_err(|_| denied())?;
        trust::pair(&s.auth.connection()?, &data, &token)
    }
    .await;
    let (status, v) = match result {
        Ok(v) => (200, v),
        Err(e) => (e.status, json!({"error":e.code})),
    };
    axum::http::Response::builder()
        .status(status)
        .header("content-type", "application/json")
        .header("cache-control", "no-store")
        .body(axum::body::Body::from(store::encoded(&v)))
        .unwrap()
}
pub async fn start(
    service: Arc<Mutex<Service>>,
    stop: Arc<AtomicBool>,
) -> Result<Option<tokio::task::JoinHandle<()>>> {
    let (root, auxiliary) = {
        let s = service.lock().map_err(|_| denied())?;
        (s.root.clone(), s.auxiliary)
    };
    let path = root.join("private/automatic-pair.bin");
    if !path.exists() {
        return Ok(None);
    }
    let state = issuer_state::load(&path, auxiliary)?;
    let kit: kit::Kit = serde_json::from_value(state["kit"].clone())?;
    let expires = state["expires"].as_i64().ok_or_else(denied)?;
    if expires <= auth::now() || complete(&service, &kit.upgrade_id)? {
        clean(&path, &root, &kit.upgrade_id)?;
        return Ok(None);
    }
    kit.validate()?;
    let tls = axum_server::tls_rustls::RustlsConfig::from_pem(
        kit.certificate_pem.as_bytes().to_vec(),
        kit.private_key_pem.as_bytes().to_vec(),
    )
    .await?;
    let listener = std::net::TcpListener::bind("192.168.4.23:8478")?;
    listener.set_nonblocking(true)?;
    let handle_server = axum_server::Handle::new();
    let shutdown = handle_server.clone();
    let state = State {
        service: service.clone(),
        peer: kit.allowed_peer.parse().map_err(|_| denied())?,
        upgrade: kit.upgrade_id.clone(),
        expires,
        slots: Arc::new(tokio::sync::Semaphore::new(4)),
    };
    let router = axum::Router::new().fallback(handle).with_state(state);
    let id = kit.upgrade_id;
    let server = axum_server::from_tcp_rustls(listener, tls)?
        .http1_only()
        .handle(handle_server);
    let capacity = crate::transport::Capacity {
        inner: server.get_ref().clone(),
        slots: Arc::new(tokio::sync::Semaphore::new(4)),
    };
    let mut server = server.acceptor(capacity);
    server
        .http_builder()
        .http1()
        .timer(hyper_util::rt::TokioTimer::new())
        .max_buf_size(16384)
        .header_read_timeout(Duration::from_secs(10));
    Ok(Some(tokio::spawn(async move {
        let guard = tokio::spawn(async move {
            while !stop.load(Ordering::SeqCst)
                && auth::now() < expires
                && !complete(&service, &id).unwrap_or(true)
            {
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
            shutdown.graceful_shutdown(Some(Duration::from_secs(5)));
            // An ordinary service restart retains the original, non-extended pairing window.
            if auth::now() >= expires || complete(&service, &id).unwrap_or(true) {
                if let Err(e) = clean(&path, &root, &id) {
                    quote_diagnostics::event(
                        "automatic.binding.cleanup_failed",
                        json!({"error":e.code}),
                    );
                }
            }
        });
        if server
            .serve(router.into_make_service_with_connect_info::<std::net::SocketAddr>())
            .await
            .is_err()
        {
            quote_diagnostics::event("automatic.binding.listener_failed", json!({}));
        }
        guard.abort();
    })))
}
fn complete(s: &Arc<Mutex<Service>>, id: &str) -> Result<bool> {
    let s = s.lock().map_err(|_| denied())?;
    Ok(s.auth.connection()?.query_row(
        "SELECT completed FROM upgrade_bindings WHERE id=?",
        [id],
        |r| r.get(0),
    )?)
}
fn clean(path: &PathBuf, root: &std::path::Path, id: &str) -> Result<()> {
    if path.exists() {
        std::fs::remove_file(path)?;
    }
    let done = root.join(format!("private/automatic-pair-{id}.done"));
    if !done.exists() {
        files::new_file(&done, b"closed")?;
    }
    Ok(())
}
