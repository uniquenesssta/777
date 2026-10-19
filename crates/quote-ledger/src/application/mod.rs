//! Transaction-local application of server-validated offline business proposals.
mod model;
mod write;
pub use model::{Line, Order};
pub use write::{apply, Change};
