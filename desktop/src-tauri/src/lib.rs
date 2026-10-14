//! Typed desktop boundary. The authenticated service remains the financial authority.
mod client;
mod journal;
mod tls;
mod types;
pub use client::Desktop;
pub use types::{Action, Connection, DesktopError, Result};
