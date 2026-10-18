//! Native operator commands for cluster membership; no secrets in arguments.
use crate::Args;
use quote_host::{
    cluster::{config, control, membership, replica},
    fail,
    host::Init,
    Error, Result,
};
use serde_json::{json, Value};
pub fn allowed(command: &str) -> Result<Vec<&'static str>> {
    let mut keys = match command {
        "resource-info" => vec![],
        "cluster-status" => vec!["--root"],
        "cluster-primary" | "cluster-invite" | "cluster-peers" => {
            vec!["--root", "--admin", "--secret-stdin"]
        }
        "cluster-revoke" => vec!["--root", "--admin", "--node-id", "--secret-stdin"],
        "cluster-join" => vec![
            "--root",
            "--invitation",
            "--backup-dir",
            "--host",
            "--bind",
            "--port",
            "--worker",
            "--notices",
        ],
        _ => return fail(422, "UNKNOWN_COMMAND"),
    };
    keys.push("--auxiliary");
    Ok(keys)
}
pub async fn execute(a: &Args) -> Result<Value> {
    if a.command == "resource-info" {
        return Ok(
            json!({"host_backend":"rust","shutdown_control":"stdin-v1","cluster_protocol":config::FORMAT}),
        );
    }
    let root = a.path("--root")?;
    let auxiliary = a.has("--auxiliary");
    match a.command.as_str() {
        "cluster-status" => replica::inspect(&root),
        "cluster-primary" => control::primary(
            &root,
            a.default("--admin", "manager"),
            &a.secret(false)?,
            auxiliary,
        ),
        "cluster-invite" | "cluster-peers" | "cluster-revoke" => {
            let (path, body) = match a.command.as_str() {
                "cluster-invite" => ("/v1/cluster/invite", json!({})),
                "cluster-peers" => ("/v1/cluster/peers", json!({})),
                _ => ("/v1/cluster/revoke", json!({"node_id":a.get("--node-id")?})),
            };
            control::admin(
                &root,
                a.default("--admin", "manager"),
                &a.secret(false)?,
                path,
                body,
            )
            .await
        }
        "cluster-join" => {
            control::join(
                Init {
                    root,
                    backups: a.path("--backup-dir")?,
                    hosts: a.options.get("--host").cloned().unwrap_or_default(),
                    bind: a.default("--bind", "127.0.0.1").into(),
                    port: a
                        .default("--port", "8477")
                        .parse()
                        .map_err(|_| Error::new(422, "HOST_CONFIG_INVALID"))?,
                    user: "manager".into(),
                    secret: membership::credential()?,
                    worker: a.path("--worker")?,
                    notices: a.path("--notices")?,
                    auxiliary,
                },
                a.get("--invitation").ok().map(std::path::Path::new),
            )
            .await
        }
        _ => fail(422, "UNKNOWN_COMMAND"),
    }
}
