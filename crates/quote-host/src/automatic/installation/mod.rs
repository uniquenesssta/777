//! Mother-install integration: a resumable replica, never an offline primary.
mod identity;
mod prepare;
mod staging;
pub use prepare::join;
pub use prepare::join_with_stop;
