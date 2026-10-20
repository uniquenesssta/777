//! Native protocol runtime only; no final installer or fabricated web assets.
#[cfg(feature = "verification")]
fn main() {
    quote_desktop::run_verification_bridge();
}
#[cfg(not(feature = "verification"))]
fn main() {
    panic!("OWNED_VERIFICATION_PROFILE_REQUIRED");
}
