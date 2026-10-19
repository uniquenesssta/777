//! Developer-side issuance journal. Candidate secrets are protected before any POST.
use super::*;
use quote_security::automatic::Package;
use std::path::Path;
pub fn status(path: &Path, auxiliary: bool) -> Result<Value> {
    if !path.exists() {
        return Ok(json!({"ready":false,"phase":"not_prepared"}));
    }
    let s = issuer_state::load(path, auxiliary)?;
    Ok(
        json!({"ready":s["binding_complete"]==true,"phase":if s["binding_complete"]==true{"ready"}else{"pending"},"site_id":s["profile"]["site_id"],"ledger_id":s["profile"]["ledger_id"],"profile":s["profile"]}),
    )
}
async fn session(s: &Value) -> Result<(crate::cluster::transport::Client, String)> {
    if s["binding_complete"] != true {
        return fail(409, "ISSUER_NOT_READY");
    }
    let connection = quote_security::automatic::connection(&s["profile"])
        .map_err(|e| Error::new(e.status, &e.code))?;
    let c = crate::cluster::transport::Client::new(&connection)?;
    let v = c
        .request(
            "/v1/automatic/issuer/session",
            s["issuer_secret"].as_str().ok_or_else(denied)?,
            &json!({"protocol":ISSUANCE,"request_id":store::uid()?,"issuer_id":s["issuer_id"]}),
        )
        .await?;
    Ok((c, v["token"].as_str().ok_or_else(denied)?.into()))
}
pub async fn issue(
    state: &Path,
    input: &Path,
    candidate: &Path,
    output: &Path,
    auxiliary: bool,
) -> Result<Value> {
    let s = issuer_state::load(state, auxiliary)?;
    let input = files::read_json(input)?;
    crate::protocol::fields(
        &input,
        &[
            "package_id",
            "delivery",
            "permissions",
            "version",
            "artifact_sha256",
        ],
        &[],
    )?;
    let id = id(&input, "package_id")?;
    let permissions: Vec<String> = serde_json::from_value(input["permissions"].clone())?;
    let delivery = input["delivery"].as_str().ok_or_else(denied)?;
    permissions::validate(delivery, &permissions)?;
    hex(&input, "artifact_sha256")?;
    if input["version"]
        .as_str()
        .is_none_or(|v| v.is_empty() || v.len() > 64 || v.chars().any(char::is_control))
    {
        return fail(422, "PACKAGE_MANIFEST_INVALID");
    }
    let record = if candidate.exists() {
        let old = issuer_state::load(candidate, auxiliary)?;
        if old["input"] != input || old["issuer_id"] != s["issuer_id"] {
            return fail(409, "PACKAGE_ID_CONFLICT");
        }
        old
    } else {
        let m = json!({"format":"777-package-manifest-v1","package_id":id,"issuer_id":s["issuer_id"],"site_id":s["profile"]["site_id"],"ledger_id":s["profile"]["ledger_id"],"trust_revision":s["profile"]["trust_revision"],"delivery":delivery,"capabilities":permissions,"node_enrollment":delivery=="manager","release_version":input["version"],"artifact_sha256":input["artifact_sha256"],"protocols":trust::protocols(),"enroll_before":auth::now()+365*86400,"max_devices":256,"max_nodes":if delivery=="manager"{128}else{0}});
        let record = json!({"input":input,"issuer_id":s["issuer_id"],"manifest":m,"secret":secret()?,"request_id":store::uid()?});
        issuer_state::save(candidate, &record, auxiliary)?;
        record
    };
    let (c, token) = session(&s).await?;
    let result=c.request("/v1/automatic/packages",&token,&json!({"protocol":ISSUANCE,"request_id":record["request_id"],"manifest":record["manifest"],"secret_hash":digest(record["secret"].as_str().ok_or_else(denied)?)?})).await?;
    if result["status"] != "active" || result["manifest"] != record["manifest"] {
        return fail(409, "PACKAGE_ISSUANCE_CONFLICT");
    }
    let bundle = Package {
        format: "777-automatic-package-v1".into(),
        profile: s["profile"].clone(),
        manifest: result["manifest"].clone(),
        secret: record["secret"].as_str().ok_or_else(denied)?.into(),
    };
    bundle
        .validate(delivery)
        .map_err(|e| Error::new(e.status, &e.code))?;
    files::replace_json(output, &serde_json::to_value(bundle)?)?;
    Ok(json!({"status":"issued","package_id":id}))
}
pub async fn close(state: &Path, candidate: &Path, auxiliary: bool) -> Result<Value> {
    let s = issuer_state::load(state, auxiliary)?;
    let record = issuer_state::load(candidate, auxiliary)?;
    let id = id(&record["manifest"], "package_id")?;
    if record["issuer_id"] != s["issuer_id"]
        || record["manifest"]["site_id"] != s["profile"]["site_id"]
        || record["manifest"]["ledger_id"] != s["profile"]["ledger_id"]
    {
        return fail(409, "PACKAGE_CLOSE_BINDING_CONFLICT");
    }
    let (c, token) = session(&s).await?;
    c.request(
        &format!("/v1/automatic/packages/{id}/close"),
        &token,
        &json!({"protocol":ISSUANCE,"request_id":store::uid()?}),
    )
    .await?;
    Ok(json!({"status":"closed","package_id":id}))
}
