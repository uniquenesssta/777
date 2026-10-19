//! HTTP dispatcher + real SQLite/auth; no claim of TLS or live SMB acceptance.
use super::*;
use axum::{
    body::{to_bytes, Body},
    extract::{ConnectInfo, State as AxumState},
    http::Request,
};
#[allow(dead_code)]
#[path = "../../tests/automatic_support/mod.rs"]
mod fixture;
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn accepted_receipt_is_durable_and_intake_progresses_with_business_mutex_held() {
    let mut f = fixture::Fixture::new();
    f.service.handle("POST","/v1/prices",&f.legacy_token,&json!({"request_id":uid().unwrap(),"expected_price_version_id":null,"prices":{"price_version_id":"http-intake","items":[{"product_id":"item","sale":"10","cost":"4","k":"1","single":true}]}}),"","fixture").unwrap();
    let (package, key, _) = f.package("sales", &["quote", "orders", "edit_orders"], 2);
    let (enrollment, secret) = f.candidate(&package);
    let session = f.activate(&enrollment, &key, &secret);
    let token = session["token"].as_str().unwrap();
    crate::intake::setup::provision(&f.service).unwrap();
    let intake = Arc::new(crate::intake::Intake::open(&f.service).unwrap().unwrap());
    let lease = intake
        .handle(
            "POST",
            "/v1/offline/lease",
            token,
            &json!({"protocol":crate::intake::FORMAT,"request_id":uid().unwrap()}),
        )
        .unwrap();
    let b = &lease["body"];
    let examples: Value = serde_json::from_str(include_str!(
        "../../../../docs/contracts/P08-02-3/examples.json"
    ))
    .unwrap();
    let mut operation = examples["operations"][0].clone();
    for field in ["site_id", "ledger_id", "device_id", "stream_id", "lease_id"] {
        operation[field] = b[field].clone();
    }
    operation["owner_id"] = b["subject"].clone();
    operation["payload"]["snapshot"]["price_version_id"] = json!("http-intake");
    operation["content_sha256"] = json!(crate::intake::envelope::digest(&operation).unwrap());
    let service = Service {
        root: f.root.clone(),
        config: f.service.config.clone(),
        ledger: f.service.ledger.clone(),
        auth: Auth::open(f.service.auth.path.clone()).unwrap(),
        devices: None,
        outputs: None,
        queries: crate::query::Queries::new().unwrap(),
        auxiliary: !cfg!(windows),
        font: None,
        test_fault: None,
    };
    let state = super::State {
        service: Arc::new(Mutex::new(service)),
        capacity: Arc::new(tokio::sync::Semaphore::new(8)),
        intake_capacity: Arc::new(tokio::sync::Semaphore::new(4)),
        backup_capacity: Arc::new(tokio::sync::Semaphore::new(1)),
        intake: Some(intake),
        backup: None,
        authorization: Arc::new(Mutex::new(())),
        peer: None,
        dirty: Arc::new(AtomicBool::new(false)),
    };
    let (lock_tx, lock_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let blocked = state.service.clone();
    let holder = std::thread::spawn(move || {
        let _lock = blocked.lock().unwrap();
        lock_tx.send(()).unwrap();
        let _ = release_rx.recv();
    });
    lock_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    let request=Request::builder().method("POST").uri("/v1/offline/operations").header("content-type","application/json").header("authorization",format!("Bearer {token}")).body(Body::from(store::encoded(&json!({"protocol":crate::intake::FORMAT,"batch_id":uid().unwrap(),"operations":[operation]})))).unwrap();
    let response = tokio::time::timeout(
        Duration::from_secs(2),
        handler(
            AxumState(state.clone()),
            ConnectInfo("127.0.0.1:12345".parse().unwrap()),
            request,
        ),
    )
    .await
    .unwrap();
    release_tx.send(()).unwrap();
    holder.join().unwrap();
    assert_eq!(response.status(), 202);
    let receipt: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), 1048576).await.unwrap()).unwrap();
    assert_eq!(receipt["receipts"][0]["state"], "received");
    let c = store::open(&f.service.ledger, false).unwrap();
    assert_eq!(
        c.query_row("SELECT count(*) FROM offline_operations", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert!(state.dirty.load(Ordering::SeqCst));
}
