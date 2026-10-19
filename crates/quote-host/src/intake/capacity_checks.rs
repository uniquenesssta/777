use super::*;
use std::time::Duration;

#[test]
fn token_refill_and_bursts_use_elapsed_time_without_scheduler_assumptions() {
    let at = Instant::now();
    for (rate, burst) in [(2.0, 2.0), (20.0, 8.0)] {
        let mut b = Bucket {
            tokens: burst,
            last: at,
        };
        for _ in 0..burst as usize {
            assert!(b.take_at(rate, burst, at));
        }
        assert!(!b.take_at(rate, burst, at));
        let next = at + Duration::from_secs_f64(1.0 / rate);
        assert!(b.take_at(rate, burst, next));
        assert!(!b.take_at(rate, burst, next));
        let later = next + Duration::from_secs(60);
        for _ in 0..burst as usize {
            assert!(b.take_at(rate, burst, later));
        }
        assert!(!b.take_at(rate, burst, later));
    }
}

#[test]
fn concurrent_device_request_is_rejected_with_retry_and_guard_is_released() {
    let c = Mutex::new(Capacity::default());
    let guard = begin(&c, "device").unwrap();
    let error = begin(&c, "device").err().unwrap();
    assert_eq!(error.status, 429);
    assert_eq!(error.retry_after, Some(1));
    drop(guard);
    assert!(!c.lock().unwrap().devices["device"].1);
    assert!(begin(&c, "other-device").is_ok());
}
