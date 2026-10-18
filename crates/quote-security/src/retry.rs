//! Delta-seconds retry policy shared by automatic protocol clients.
/// Back off transient failures, probe denied/conflicting bindings slowly, and honor server minima.
pub fn delay(attempt: u32, blocked: bool, retry_after: Option<u64>, entropy: u8) -> u64 {
    let base = if blocked {
        300
    } else {
        2u64.saturating_pow(attempt.min(8)).min(300)
    };
    let jitter = base.saturating_mul(u64::from(entropy)) / 1024;
    base.saturating_add(jitter)
        .min(300)
        .max(retry_after.unwrap_or(0))
}
#[cfg(test)]
mod tests {
    use super::delay;
    #[test]
    fn an_unavailable_host_gets_backoff_and_a_denied_identity_never_rapidly_reenrolls() {
        let delays: Vec<_> = (1..20).map(|n| delay(n, false, None, 255)).collect();
        assert_eq!(delays[0], 2);
        assert!(delays.windows(2).all(|p| p[0] <= p[1]));
        assert_eq!(delays.last(), Some(&300));
        assert_eq!(delay(1, true, None, 0), 300);
        assert_eq!(delay(1, false, Some(600), 0), 600);
        assert_ne!(delay(5, false, None, 0), delay(5, false, None, 255));
    }
}
