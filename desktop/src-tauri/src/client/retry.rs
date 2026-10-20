//! Native retry gate: UI polling cannot accelerate enrollment or change a blocked identity.
use super::*;
use std::time::{Duration, Instant};
#[derive(Default)]
pub(super) struct AutomaticRetry {
    attempt: u32,
    next: Option<Instant>,
    transient: bool,
}
impl AutomaticRetry {
    pub fn ready(&self) -> Result<()> {
        if self.next.is_some_and(|next| Instant::now() < next) {
            return Err(DesktopError::new(503, "AUTOMATIC_RETRY_WAITING"));
        }
        Ok(())
    }
    pub fn record(&mut self, result: &Result<Value>) {
        if let Err(error) = result {
            self.transient = error.status == 0 || error.status >= 500;
            self.attempt = self.attempt.saturating_add(1);
            let mut entropy = [0u8];
            let _ = getrandom::getrandom(&mut entropy);
            let delay = quote_security::retry::delay(
                self.attempt,
                matches!(error.status, 401 | 403 | 409 | 422 | 426),
                error.retry_after,
                entropy[0],
            );
            self.next = Some(Instant::now() + Duration::from_secs(delay));
        } else {
            self.attempt = 0;
            self.next = None;
        }
    }
    pub(super) fn reconnected(&mut self) {
        if self.transient {
            self.next = None;
            self.attempt = 0;
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn polling_cannot_bypass_a_failed_enrollment_or_clear_its_retry_gate() {
        let mut retry = AutomaticRetry::default();
        retry.record(&Err(DesktopError::new(
            403,
            "AUTOMATIC_AUTHORIZATION_DENIED",
        )));
        assert_eq!(retry.ready().unwrap_err().code, "AUTOMATIC_RETRY_WAITING");
        assert!(retry.next.unwrap() > Instant::now() + Duration::from_secs(290));
        retry.reconnected();
        assert!(retry.ready().is_err());
        retry.record(&Ok(Value::Null));
        retry.ready().unwrap();
    }
    #[test]
    fn a_network_reconnection_wakes_transient_failure_without_bypassing_rate_limits() {
        let mut retry = AutomaticRetry::default();
        retry.record(&Err(DesktopError::new(0, "SERVICE_UNREACHABLE")));
        assert!(retry.ready().is_err());
        retry.reconnected();
        retry.ready().unwrap();
        retry.record(&Err(DesktopError::new(429, "CAPACITY")));
        retry.reconnected();
        assert!(retry.ready().is_err());
    }
}
