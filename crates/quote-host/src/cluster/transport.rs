use super::config::Config;
use crate::{fail, Error, Result};
use quote_security::Connection;
use serde_json::{json, Value};
pub struct Client {
    http: reqwest::Client,
    connection: Connection,
}
impl Client {
    pub fn new(connection: &Connection) -> Result<Self> {
        Ok(Self {
            http: quote_security::tls::build(connection)
                .map_err(|e| Error::new(e.status, &e.code))?,
            connection: connection.clone(),
        })
    }
    pub async fn request(&self, path: &str, token: &str, data: &Value) -> Result<Value> {
        if !path.starts_with("/v1/") || path.contains('?') || path.contains('#') {
            return fail(422, "CLUSTER_PATH_INVALID");
        }
        let raw = serde_json::to_vec(data)?;
        if raw.len() > 2 * crate::protocol::BODY_LIMIT {
            return fail(413, "BODY_TOO_LARGE");
        }
        let mut request = self
            .http
            .post(format!(
                "{}{}",
                self.connection.url.trim_end_matches('/'),
                path
            ))
            .header("Content-Type", "application/json")
            .body(raw);
        if !token.is_empty() {
            request = request.bearer_auth(token);
        }
        let mut response = request
            .send()
            .await
            .map_err(|_| Error::new(503, "CLUSTER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED"))?;
        let status = response.status().as_u16();
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| Error::new(503, "CLUSTER_RESPONSE_INCOMPLETE"))?
        {
            if bytes.len() + chunk.len() > 8 * crate::protocol::BODY_LIMIT {
                return fail(413, "CLUSTER_RESPONSE_TOO_LARGE");
            }
            bytes.extend_from_slice(&chunk);
        }
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|_| Error::new(502, "CLUSTER_RESPONSE_INVALID"))?;
        if status != 200 {
            let code = value["error"]
                .as_str()
                .filter(|s| {
                    s.len() <= 128
                        && s.bytes()
                            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
                })
                .unwrap_or("CLUSTER_REQUEST_FAILED");
            return fail(status, code);
        }
        Ok(value)
    }
}
pub struct Peer {
    pub config: Config,
    pub credential: String,
    pub client: Client,
}
impl Peer {
    pub fn new(config: &Config, credential: String) -> Result<Self> {
        Ok(Self {
            config: config.clone(),
            credential,
            client: Client::new(&config.primary)?,
        })
    }
    pub async fn request(&self, path: &str, mut body: Value) -> Result<Value> {
        let object = body
            .as_object_mut()
            .ok_or_else(|| Error::new(422, "CLUSTER_BODY_INVALID"))?;
        object.insert("node_id".into(), json!(self.config.node_id));
        object.insert("cluster_id".into(), json!(self.config.cluster_id));
        object.insert("ledger_id".into(), json!(self.config.ledger_id));
        self.client.request(path, &self.credential, &body).await
    }
    pub async fn forward(
        &self,
        method: &str,
        path: &str,
        query: &str,
        token: &str,
        body: &Value,
    ) -> Result<Value> {
        self.request(
            "/v1/cluster/forward",
            json!({"method":method,"path":path,"query":query,"authorization":token,"body":body}),
        )
        .await
    }
}
