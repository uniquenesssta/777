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
mod client;
#[cfg(all(
    debug_assertions,
    not(any(feature = "manager", feature = "sales", feature = "verification"))
))]
mod developer;
mod journal;
mod output_folder;
mod startup;
mod tls;
mod types;
pub use client::Desktop;
pub use startup::delivery;
pub use startup::formal_profile_root;
#[cfg(quote777_packaged)]
pub use startup::package_info;
pub use types::{Action, Connection, DesktopError, Result};
