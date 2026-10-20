//! Primary-only bounded business application and developer-authorized decisions.
mod authorization;
mod changes;
mod cursor;
mod engine;
mod history;
mod merge;
mod plan;
mod projection;
pub mod provision;
mod resolution;
mod review;
mod review_read;
pub(super) use engine::apply;
pub(super) use engine::state as engine_state;
pub(super) use engine::wake;
pub(super) fn enabled(i: &super::Intake) -> bool {
    i.config["mode"] == "apply"
}
pub(super) fn api(
    i: &super::Intake,
    method: &str,
    path: &str,
    token: &str,
    data: &serde_json::Value,
) -> crate::Result<serde_json::Value> {
    review::handle(i, method, path, token, data)
}
pub(super) use changes::handle as changes;
