#[cfg(all(feature = "manager", feature = "sales"))]
compile_error!("DELIVERY_FEATURE_CONFLICT");
#[cfg(all(
    not(debug_assertions),
    not(feature = "verification"),
    not(feature = "manager"),
    not(feature = "sales")
))]
compile_error!(
    "RELEASE_DELIVERY_REQUIRED: select manager or sales; verification is for isolated checks only"
);
// Typed desktop boundary. The authenticated service remains the financial authority.
#[cfg(windows)]
pub mod background;
mod client;
mod connection_file;
#[cfg(all(
    debug_assertions,
    not(any(feature = "manager", feature = "sales", feature = "verification"))
))]
mod developer;
mod directory_preference;
mod journal;
mod offline;
mod output_folder;
mod permissions;
mod request_boundary;
mod startup;
mod tls;
mod types;
#[cfg(feature = "verification")]
mod verification;
pub use client::Desktop;
pub use startup::delivery;
pub use startup::formal_profile_root;
#[cfg(quote777_packaged)]
pub use startup::package_info;
pub use types::{Action, Connection, DesktopError, Result, UiErrorKind, UiEvent, UiSource};
#[cfg(feature = "verification")]
pub use verification::run as run_verification_bridge;
