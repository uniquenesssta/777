//! Pinned first-contact surface; only signed package registration is exposed.
use super::*;
use crate::service::Service;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
#[derive(Clone)]
struct State {
    service: Arc<Mutex<Service>>,
    provision: Value,
    dirty: Arc<AtomicBool>,
    slots: Arc<tokio::sync::Semaphore>,
}
async fn handle(
    axum::extract::State(state): axum::extract::State<State>,
    axum::extract::ConnectInfo(peer): axum::extract::ConnectInfo<std::net::SocketAddr>,
    req: axum::extract::Request,
) -> axum::response::Response {
    let result = async {
        let _slot = state
            .slots
            .try_acquire()
            .map_err(|_| Error::new(429, "AUTOMATIC_RATE_LIMIT"))?;
        if req.method() != "POST"
            || req.uri().path() != quote_security::local_package::PATH
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
        let raw = tokio::time::timeout(
            Duration::from_secs(10),
            axum::body::to_bytes(req.into_body(), 65536),
        )
        .await
        .map_err(|_| Error::new(408, "BODY_TIMEOUT"))?
        .map_err(|_| Error::new(413, "BODY_TOO_LARGE"))?;
        let data = crate::protocol::decode(&raw, 65536)?;
        super::api::rate(&peer.ip().to_string(), "local-package-registration")?;
        let package: quote_security::automatic::Package = serde_json::from_value(data)?;
        let s = state.service.lock().map_err(|_| denied())?;
        if crate::cluster::config::read(&s.root)?
            .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
        {
            return Err(denied());
        }
        let bound = registration::register(&s.auth.connection()?, &state.provision, &package)?;
        state.dirty.store(true, Ordering::SeqCst);
        Ok(serde_json::to_value(bound)?)
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
    dirty: Arc<AtomicBool>,
) -> Result<Option<tokio::task::JoinHandle<()>>> {
    let (root, auxiliary) = {
        let s = service.lock().map_err(|_| denied())?;
        (s.root.clone(), s.auxiliary)
    };
    let path = root.join("private/automatic-bootstrap.bin");
    if !path.exists() {
        return Ok(None);
    }
    let provision = issuer_state::load(&path, auxiliary)?;
    registration::validate_provision(&provision)?;
    let listener = std::net::TcpListener::bind("192.168.4.23:8479")?;
    Ok(Some(
        listen(service, stop, dirty, provision, listener).await?,
    ))
}
async fn listen(
    service: Arc<Mutex<Service>>,
    stop: Arc<AtomicBool>,
    dirty: Arc<AtomicBool>,
    provision: Value,
    listener: std::net::TcpListener,
) -> Result<tokio::task::JoinHandle<()>> {
    let tls = axum_server::tls_rustls::RustlsConfig::from_pem(
        provision["profile"]["tls"]["certificate_pem"]
            .as_str()
            .ok_or_else(denied)?
            .as_bytes()
            .to_vec(),
        provision["private_key_pem"]
            .as_str()
            .ok_or_else(denied)?
            .as_bytes()
            .to_vec(),
    )
    .await?;
    listener.set_nonblocking(true)?;
    let handle_server = axum_server::Handle::new();
    let shutdown = handle_server.clone();
    let state = State {
        service: service.clone(),
        provision,
        dirty,
        slots: Arc::new(tokio::sync::Semaphore::new(4)),
    };
    let router = axum::Router::new().fallback(handle).with_state(state);
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
    Ok(tokio::spawn(async move {
        let guard = tokio::spawn(async move {
            while !stop.load(Ordering::SeqCst) {
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
            shutdown.graceful_shutdown(Some(Duration::from_secs(5)));
        });
        if server
            .serve(router.into_make_service_with_connect_info::<std::net::SocketAddr>())
            .await
            .is_err()
        {
            quote_diagnostics::event("automatic.registration.listener_failed", json!({}));
        }
        guard.abort();
    }))
}

#[cfg(test)]
#[path = "bootstrap_tests.rs"]
mod tests;
