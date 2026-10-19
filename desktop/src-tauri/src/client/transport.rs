use super::*;
pub(super) async fn request(
    s: &Session,
    method: &str,
    path: &str,
    body: Option<&Value>,
) -> Result<Value> {
    request_with_package(s, method, path, body, None).await
}
pub(super) async fn request_with_package(
    s: &Session,
    method: &str,
    path: &str,
    body: Option<&Value>,
    package: Option<&str>,
) -> Result<Value> {
    let bytes = body
        .map(serde_json::to_vec)
        .transpose()
        .map_err(|_| DesktopError::new(422, "INVALID_BODY"))?;
    if bytes.as_ref().is_some_and(|b| b.len() > REQUEST_LIMIT) {
        return Err(DesktopError::new(413, "BODY_TOO_LARGE"));
    }
    let mut req = s
        .http
        .request(
            reqwest::Method::from_bytes(method.as_bytes())
                .map_err(|_| DesktopError::new(422, "INVALID_METHOD"))?,
            format!("{}{}", s.connection.url.trim_end_matches('/'), path),
        )
        .header("Accept", "application/json");
    if quote_diagnostics::enabled() {
        req = req.header("X-777-Execution-Id", quote_diagnostics::execution_id());
    }
    if !s.token.is_empty() {
        req = req.bearer_auth(&s.token);
    }
    if let Some(secret) = package {
        req = req.header("X-777-Package-Authorization", format!("Bearer {secret}"));
    }
    if let Some(bytes) = bytes {
        req = req.header("Content-Type", "application/json").body(bytes);
    }
    let mut response = req.send().await.map_err(|e| {
        #[cfg(feature = "verification")]
        eprintln!("verification TLS failure: {e:?}");
        let _ = e;
        DesktopError::new(0, "SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED")
    })?;
    let status = response.status().as_u16();
    let retry_after = response
        .headers()
        .get("Retry-After")
        .and_then(|h| h.to_str().ok())
        .and_then(|s| s.parse::<u64>().ok())
        .map(|s| s.min(86400));
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| DesktopError::new(0, "SERVICE_RESPONSE_INCOMPLETE"))?
    {
        if bytes.len() + chunk.len() > 8 * REQUEST_LIMIT {
            return Err(DesktopError::new(413, "SERVICE_RESPONSE_TOO_LARGE"));
        }
        bytes.extend_from_slice(&chunk);
    }
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| DesktopError::new(502, "SERVICE_RESPONSE_INVALID"))?;
    if status != 200 {
        let mut error = DesktopError::new(
            status,
            value["error"]
                .as_str()
                .unwrap_or("SERVICE_RESPONSE_INVALID"),
        );
        error.retry_after = retry_after;
        return Err(error);
    }
    Ok(value)
}
