//! Protected developer-side state, persisted before network acknowledgements.
use super::*;
use std::path::Path;
pub fn save(path: &Path, value: &Value, auxiliary: bool) -> Result<()> {
    let raw = quote_security::protect::protect(&serde_json::to_vec(value)?, true, auxiliary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    let stage = path.with_extension(format!("{}.partial", store::uid()?));
    let result = (|| {
        files::new_file(&stage, &raw)?;
        std::fs::rename(&stage, path)?;
        Ok(())
    })();
    if stage.exists() {
        let _ = std::fs::remove_file(stage);
    }
    result
}
pub fn load(path: &Path, auxiliary: bool) -> Result<Value> {
    let raw = quote_security::protect::protect(&files::read(path, 256 * 1024)?, false, auxiliary)
        .map_err(|e| Error::new(e.status, &e.code))?;
    crate::protocol::decode(&raw, 256 * 1024)
}
async fn post(
    connection: &quote_security::Connection,
    path: &str,
    token: &str,
    body: &Value,
) -> Result<Value> {
    let client = crate::cluster::transport::Client::new(connection)?;
    client.request(path, token, body).await
}
pub async fn connect(path: &Path, auxiliary: bool) -> Result<Value> {
    let mut state = load(path, auxiliary)?;
    if state["format"] != "777-issuer-pending-v1" {
        return fail(422, "ISSUER_STATE_INVALID");
    }
    let body = json!({"protocol":ISSUANCE,"request_id":store::uid()?,"upgrade_id":state["upgrade_id"],"challenge":state["challenge"]});
    if state["profile"].is_null() {
        let temporary: quote_security::Connection =
            serde_json::from_value(state["temporary_connection"].clone())?;
        let result = post(
            &temporary,
            "/v1/automatic/binding/pair",
            state["pair_secret"].as_str().ok_or_else(denied)?,
            &body,
        )
        .await?;
        if result["upgrade_id"] != state["upgrade_id"]
            || result["issuer_id"] != state["issuer_id"]
            || result["challenge"] != state["challenge"]
            || result["profile"]["primary_url"] != trust::PRIMARY
            || result["profile"]["required_protocols"] != trust::protocols()
        {
            return fail(409, "UPGRADE_BINDING_CONFLICT");
        }
        let profile = &result["profile"];
        store::id(profile["site_id"].as_str().ok_or_else(denied)?)?;
        store::id(profile["ledger_id"].as_str().ok_or_else(denied)?)?;
        let connection = connection(profile)?;
        quote_security::tls::configuration(&connection)
            .map_err(|e| Error::new(e.status, &e.code))?;
        state["profile"] = profile.clone();
        save(path, &state, auxiliary)?;
    }
    let connection = connection(&state["profile"])?;
    let login = post(
        &connection,
        "/v1/automatic/issuer/session",
        state["issuer_secret"].as_str().ok_or_else(denied)?,
        &json!({"protocol":ISSUANCE,"request_id":store::uid()?,"issuer_id":state["issuer_id"]}),
    )
    .await?;
    post(
        &connection,
        "/v1/automatic/binding/confirm",
        login["token"].as_str().ok_or_else(denied)?,
        &body,
    )
    .await?;
    state["pair_secret"] = Value::Null;
    state["temporary_connection"] = Value::Null;
    state["binding_complete"] = json!(true);
    save(path, &state, auxiliary)?;
    Ok(
        json!({"status":"issuer_ready","site_id":state["profile"]["site_id"],"ledger_id":state["profile"]["ledger_id"]}),
    )
}
pub fn connection(profile: &Value) -> Result<quote_security::Connection> {
    Ok(quote_security::Connection {
        url: profile["primary_url"].as_str().ok_or_else(denied)?.into(),
        certificate_pem: profile["tls"]["certificate_pem"]
            .as_str()
            .ok_or_else(denied)?
            .into(),
        certificate_sha256: profile["tls"]["certificate_sha256"]
            .as_str()
            .ok_or_else(denied)?
            .into(),
    })
}
