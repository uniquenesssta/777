use super::*;
#[path = "test_server.rs"]
mod server;
fn client() -> (Desktop, PathBuf) {
    let root = std::env::temp_dir().join(format!("777-pending-{}", new_id().unwrap()));
    (Desktop::new(root.clone(), !cfg!(windows)).unwrap(), root)
}
fn pending(s: &Session, path: String) -> Pending {
    Pending {
        path,
        body: json!({"request_id":new_id().unwrap()}),
        subject: s.subject.clone(),
        url: s.connection.url.clone(),
        pin: s.connection.certificate_sha256.clone(),
    }
}
#[tokio::test]
async fn denied_path_is_rejected_before_journal_and_output_routes_keep_permissions() {
    let (mut d, root) = client();
    let (session, worker) = server::session(vec![]);
    d.session = Some(session);
    assert_eq!(
        d.mutate("/v1/not-an-allowed-mutation", json!({}))
            .await
            .unwrap_err()
            .code,
        "PACKAGE_PERMISSION_DENIED"
    );
    assert!(!d.has_pending().unwrap());
    for op in ["delete", "retry"] {
        let path = format!("/v1/outputs/{}/{op}", new_id().unwrap());
        assert!(permissions::pending(&None, &path, &json!({})).is_ok());
        assert!(permissions::pending(&Some(vec!["quote".into()]), &path, &json!({})).is_err());
    }
    assert!(permissions::pending(&None, "/v1/outputs/bad/delete", &json!({})).is_err());
    worker.join().unwrap();
    drop(d);
    std::fs::remove_dir_all(root).unwrap();
}
#[tokio::test]
async fn old_delete_journal_reopens_and_replays_the_same_request_then_unlocks() {
    let (mut d, root) = client();
    let (session, worker) = server::session(vec![
        (200, json!({"result":null})),
        (200, json!({"deleted":true})),
    ]);
    let p = pending(
        &session,
        format!("/v1/outputs/{}/delete", new_id().unwrap()),
    );
    d.store.write("pending.bin", &p).unwrap();
    d.session = Some(session.clone());
    drop(d);
    let mut d = Desktop::new(root.clone(), !cfg!(windows)).unwrap();
    d.session = Some(session);
    let result = d.execute(Action::Recover { retry: true }).await.unwrap();
    assert_eq!(result["pending"], false);
    assert_eq!(result["result"]["deleted"], true);
    assert!(!d.has_pending().unwrap());
    let requests = worker.join().unwrap();
    assert_eq!(requests[1], (p.path, p.body));
    drop(d);
    std::fs::remove_dir_all(root).unwrap();
}
#[tokio::test]
async fn unknown_delete_keeps_journal_but_definitive_host_rejection_unlocks() {
    let (mut d, root) = client();
    let (session, worker) = server::session(vec![
        (503, json!({"error":"TEMPORARY"})),
        (200, json!({"result":null})),
        (404, json!({"error":"NOT_FOUND"})),
    ]);
    d.session = Some(session);
    let path = format!("/v1/outputs/{}/delete", new_id().unwrap());
    assert_eq!(
        d.mutate(&path, json!({})).await.unwrap_err().code,
        "COMMIT_UNKNOWN"
    );
    assert!(d.has_pending().unwrap());
    assert_eq!(
        d.execute(Action::Recover { retry: true })
            .await
            .unwrap_err()
            .code,
        "NOT_FOUND"
    );
    assert!(!d.has_pending().unwrap());
    let requests = worker.join().unwrap();
    assert_eq!(requests[0], requests[2]);
    drop(d);
    std::fs::remove_dir_all(root).unwrap();
}
