//! Compile-time obligations used by the native multithreaded executor.
//! No UI, network, or Windows runtime validation is implied by this check.
use super::*;

const _: fn(&mut Desktop) = |desktop| {
    fn require_send<T: std::future::Future + Send>(future: T) {
        drop(future);
    }
    require_send(desktop.execute(Action::Bootstrap {}));
    require_send(desktop.directory_context("developer_root"));
    require_send(desktop.sync_tick());
};
