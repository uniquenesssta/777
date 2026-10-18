use crate::{
    automatic::*,
    cluster::{config, transport::Client},
    Result,
};
use quote_security::automatic::Package;
use serde_json::{json, Value};
use std::path::Path;
pub async fn enroll(state: &Path, root: &Path, p: &Package, auxiliary: bool) -> Result<Value> {
    let path = state.join("node.bin");
    let existing = config::read(root)?;
    let mut node = if path.exists() {
        issuer_state::load(&path, auxiliary)?
    } else {
        let (id, key, legacy) = if let Some(c) = &existing {
            if c.role != config::Role::Replica
                || c.ledger_id != p.profile["ledger_id"]
                || c.primary.certificate_sha256 != p.profile["tls"]["certificate_sha256"]
            {
                return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
            }
            (c.node_id.clone(), config::secret(root, auxiliary)?, true)
        } else {
            (store::uid()?, secret()?, false)
        };
        let value = json!({"root":root,"node_id":id,"secret":key,"package_id":p.manifest["package_id"],"site_id":p.profile["site_id"],"ledger_id":p.profile["ledger_id"],"legacy":legacy,"request_id":store::uid()?});
        issuer_state::save(&path, &value, auxiliary)?;
        value
    };
    if node["root"] != json!(root)
        || node["site_id"] != p.profile["site_id"]
        || node["ledger_id"] != p.profile["ledger_id"]
    {
        return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    let client = Client::new(
        &p.validate("manager")
            .map_err(|e| crate::Error::new(e.status, &e.code))?,
    )?;
    let mut body = json!({"protocol":ENROLLMENT,"request_id":node["request_id"],"site_id":p.profile["site_id"],"ledger_id":p.profile["ledger_id"],"node_id":node["node_id"],"node_secret_hash":digest(node["secret"].as_str().ok_or_else(denied)?)?,"package_id":p.manifest["package_id"]});
    let joined = if node["legacy"] == true {
        client
            .request_with_package(
                "/v1/automatic/nodes/adopt",
                node["secret"].as_str().ok_or_else(denied)?,
                &body,
                Some(&p.secret),
            )
            .await?
    } else {
        if node["package_id"] != p.manifest["package_id"] {
            client.request_with_package("/v1/automatic/nodes/upgrade",node["secret"].as_str().ok_or_else(denied)?,&json!({"protocol":ENROLLMENT,"request_id":node["request_id"],"node_id":node["node_id"],"package_id":p.manifest["package_id"]}),Some(&p.secret)).await?;
        }
        let permit = client
            .request("/v1/automatic/nodes/permit", &p.secret, &body)
            .await?;
        body.as_object_mut().unwrap().remove("package_id");
        client
            .request(
                "/v1/automatic/nodes/enroll",
                permit["permit"].as_str().ok_or_else(denied)?,
                &body,
            )
            .await?
    };
    if joined["ledger_id"] != p.profile["ledger_id"]
        || joined["node_id"] != node["node_id"]
        || joined["snapshot_protocol"] != "777-cluster-snapshot-v2"
        || joined["primary"]
            != serde_json::to_value(
                p.validate("manager")
                    .map_err(|e| crate::Error::new(e.status, &e.code))?,
            )?
    {
        return crate::fail(409, "CLUSTER_IDENTITY_CONFLICT");
    }
    node["legacy"] = json!(false);
    node["package_id"] = p.manifest["package_id"].clone();
    node["request_id"] = json!(store::uid()?);
    node["joined"] = joined;
    issuer_state::save(&path, &node, auxiliary)?;
    Ok(node)
}
