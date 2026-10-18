use super::*;
use crate::service::Service;
use std::{
    collections::HashMap,
    sync::{Mutex, OnceLock},
};
pub(super) fn rate(peer: &str, token: &str) -> Result<()> {
    static LIMIT: OnceLock<Mutex<HashMap<String, (i64, u32)>>> = OnceLock::new();
    let mut map = LIMIT
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| denied())?;
    let now = auth::now();
    map.retain(|_, (at, _)| now - *at < 60);
    for key in [
        format!("peer:{peer}"),
        format!("credential:{}", store::hash(token)),
    ] {
        if !map.contains_key(&key) && map.len() >= 8192 {
            return fail(429, "AUTOMATIC_RATE_LIMIT");
        }
        let value = map.entry(key).or_insert((now, 0));
        value.1 += 1;
        if value.1 > 120 {
            return fail(429, "AUTOMATIC_RATE_LIMIT");
        }
    }
    Ok(())
}
pub fn handle(
    s: &Service,
    method: &str,
    path: &str,
    token: &str,
    package_token: &str,
    data: &Value,
    peer: &str,
) -> Result<Value> {
    rate(peer, token)?;
    if serde_json::to_vec(data)?.len() > 65536 {
        return fail(413, "BODY_TOO_LARGE");
    }
    if crate::cluster::config::read(&s.root)?
        .is_some_and(|c| c.role == crate::cluster::config::Role::Replica)
    {
        return fail(409, "CLUSTER_REPLICA_CANNOT_WRITE");
    }
    let c = s.auth.connection()?;
    if !schema::enabled(&c)? {
        return fail(426, "PROTOCOL_UPGRADE_REQUIRED");
    }
    if method == "GET" && path == "/v1/automatic/capabilities" {
        return capabilities(&c);
    }
    if method == "POST" {
        match path {
            "/v1/automatic/devices/adopt" => {
                return legacy_device::adopt(s, &c, data, token, package_token)
            }
            "/v1/automatic/issuer/session" => return sessions::issuer_session(&c, data, token),
            "/v1/automatic/devices/enroll" => return devices::enroll(&c, data, token),
            "/v1/automatic/devices/session" => return devices::session(&c, data, token),
            "/v1/automatic/devices/upgrade" => {
                return devices::upgrade(&c, data, token, package_token)
            }
            "/v1/automatic/nodes/permit" => return nodes::permit(&s.root, &c, data, token),
            "/v1/automatic/nodes/enroll" => return nodes::enroll(&s.root, &c, data, token),
            "/v1/automatic/nodes/adopt" => {
                return nodes::adopt(&s.root, &c, data, token, package_token)
            }
            "/v1/automatic/nodes/upgrade" => return nodes::upgrade(&c, data, token, package_token),
            "/v1/automatic/binding/confirm" => return trust::confirm(&c, data, token),
            _ => (),
        }
    }
    let ctx = sessions::lookup(&c, token)?;
    if ctx.kind != "issuer" {
        return Err(denied());
    }
    if method == "POST" && path == "/v1/automatic/packages" {
        return packages::create(&c, &ctx.id, data);
    }
    let pieces = path
        .strip_prefix("/v1/automatic/packages/")
        .unwrap_or("")
        .split('/')
        .collect::<Vec<_>>();
    match (method, pieces.as_slice()) {
        ("GET", [id]) => packages::listing(&c, &ctx.id, id),
        ("POST", [id, "close"]) => packages::close(&c, &ctx.id, id, data, false),
        ("POST", [id, "revoke"]) => packages::close(&c, &ctx.id, id, data, true),
        _ => fail(404, "NOT_FOUND"),
    }
}
