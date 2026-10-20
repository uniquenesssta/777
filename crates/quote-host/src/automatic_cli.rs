//! Local owner/issuer operations. No password, issuer key or ticket in arguments.
use crate::Args;
use quote_host::{automatic as a, fail, files, service::Service, Result};
use serde_json::{json, Value};
pub fn allowed(command: &str) -> Result<Vec<&'static str>> {
    let mut keys = match command {
        "automatic-package-check" => vec!["--package"],
        "automatic-local-status" => vec!["--state"],
        "automatic-local-issue" => vec!["--state", "--input", "--candidate", "--output"],
        "automatic-host-trust" => vec!["--state", "--output"],
        "automatic-host-update" => vec!["--root", "--provision", "--notices"],
        "automatic-prepare" => vec!["--output", "--state", "--peer", "--notices"],
        "automatic-connect" => vec!["--state"],
        "automatic-issuer-status" => vec!["--state"],
        "automatic-issue" => vec!["--state", "--input", "--candidate", "--output"],
        "automatic-close" => vec!["--state", "--candidate"],
        "automatic-node-join" => vec![
            "--shutdown-stdin",
            "--state",
            "--root",
            "--package",
            "--backup-dir",
            "--worker",
            "--notices",
        ],
        "automatic-upgrade" => vec!["--root", "--kit", "--notices"],
        "automatic-revoke" => vec!["--root", "--kind", "--id"],
        _ => return fail(422, "UNKNOWN_COMMAND"),
    };
    keys.push("--auxiliary");
    Ok(keys)
}
pub async fn execute(args: &Args) -> Result<Value> {
    let auxiliary = args.has("--auxiliary");
    match args.command.as_str() {
        "automatic-package-check" => {
            let p: quote_security::automatic::Package =
                serde_json::from_slice(&files::read(&args.path("--package")?, 131072)?)?;
            p.validate("manager")
                .map_err(|e| quote_host::Error::new(e.status, &e.code))?;
            let caps: Vec<String> = serde_json::from_value(p.manifest["capabilities"].clone())?;
            a::permissions::validate("manager", &caps)?;
            Ok(json!({"status":"package_validated","delivery":"manager"}))
        }
        "automatic-local-status" => a::local_issuer::status(&args.path("--state")?, auxiliary),
        "automatic-local-issue" => a::local_issuer::issue(
            &args.path("--state")?,
            &args.path("--input")?,
            &args.path("--candidate")?,
            &args.path("--output")?,
            auxiliary,
        ),
        "automatic-host-trust" => {
            a::local_issuer::provision(&args.path("--state")?, &args.path("--output")?, auxiliary)
        }
        "automatic-host-update" => a::registration::install(
            &args.path("--root")?,
            &args.path("--provision")?,
            &args.path("--notices")?,
            auxiliary,
        ),
        "automatic-prepare" => a::kit::prepare(
            &args.path("--output")?,
            &args.path("--state")?,
            args.get("--peer")?,
            &args.path("--notices")?,
            auxiliary,
        ),
        "automatic-connect" => a::issuer_state::connect(&args.path("--state")?, auxiliary).await,
        "automatic-issuer-status" => a::issuance::status(&args.path("--state")?, auxiliary),
        "automatic-issue" => {
            a::issuance::issue(
                &args.path("--state")?,
                &args.path("--input")?,
                &args.path("--candidate")?,
                &args.path("--output")?,
                auxiliary,
            )
            .await
        }
        "automatic-close" => {
            a::issuance::close(
                &args.path("--state")?,
                &args.path("--candidate")?,
                auxiliary,
            )
            .await
        }
        "automatic-node-join" => {
            let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
            if args.has("--shutdown-stdin") {
                let stopped = stop.clone();
                std::thread::spawn(move || {
                    let mut byte = [0];
                    let _ = std::io::Read::read(&mut std::io::stdin(), &mut byte);
                    stopped.store(true, std::sync::atomic::Ordering::SeqCst);
                });
            }
            a::installation::join_with_stop(
                quote_host::host::Init {
                    root: args.path("--root")?,
                    backups: args.path("--backup-dir")?,
                    hosts: vec!["127.0.0.1".into(), "localhost".into()],
                    bind: "127.0.0.1".into(),
                    port: 8477,
                    user: "replica-local".into(),
                    secret: String::new(),
                    worker: args.path("--worker")?,
                    notices: args.path("--notices")?,
                    auxiliary,
                },
                &args.path("--state")?,
                &args.path("--package")?,
                &stop,
            )
            .await
        }
        "automatic-upgrade" => a::upgrade::apply(
            &args.path("--root")?,
            &args.path("--kit")?,
            &args.path("--notices")?,
            auxiliary,
        ),
        "automatic-revoke" => {
            let root = args.path("--root")?;
            let _owner = files::Owner::acquire(&root)?;
            a::deployment::verify(&root, auxiliary)?;
            let s = Service::load(&root, auxiliary, true)?;
            if quote_host::cluster::config::read(&root)?
                .is_some_and(|c| c.role == quote_host::cluster::config::Role::Replica)
            {
                return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
            }
            let c = s.auth.connection()?;
            let id = args.get("--id")?;
            quote_ledger::store::id(id)?;
            if args.get("--kind")? == "device" {
                return a::devices::revoke(&c, id);
            }
            let tx = c.unchecked_transaction()?;
            let changed = match args.get("--kind")? {
                "node" => tx.execute(
                    "UPDATE automatic_nodes SET state='revoked' WHERE id=?",
                    [id],
                )?,
                "issuer" => {
                    tx.execute(
                        "UPDATE package_grants SET status='revoked' WHERE issuer_id=?",
                        [id],
                    )?;
                    tx.execute(
                        "UPDATE issuers SET enabled=0,epoch=epoch+1 WHERE id=?",
                        [id],
                    )?
                }
                "package" => tx.execute(
                    "UPDATE package_grants SET status='revoked' WHERE id=?",
                    [id],
                )?,
                _ => return fail(422, "AUTOMATIC_REVOKE_KIND_INVALID"),
            };
            if changed != 1 {
                return fail(404, "NOT_FOUND");
            }
            a::audit(&tx, "local-owner", "authorization.revoked", id)?;
            tx.commit()?;
            Ok(json!({"revoked":true}))
        }
        _ => fail(422, "UNKNOWN_COMMAND"),
    }
}
