use super::*;
use std::{collections::HashMap, time::Instant};
struct Bucket {
    tokens: f64,
    last: Instant,
}
impl Bucket {
    fn new(tokens: f64) -> Self {
        Self {
            tokens,
            last: Instant::now(),
        }
    }
    fn take(&mut self, rate: f64, burst: f64) -> bool {
        self.take_at(rate, burst, Instant::now())
    }
    fn take_at(&mut self, rate: f64, burst: f64, now: Instant) -> bool {
        self.tokens = (self.tokens + now.duration_since(self.last).as_secs_f64() * rate).min(burst);
        self.last = now;
        if self.tokens < 1.0 {
            return false;
        }
        self.tokens -= 1.0;
        true
    }
}
#[cfg(test)]
#[path = "capacity_checks.rs"]
mod tests;
pub(super) struct Capacity {
    global: Bucket,
    devices: HashMap<String, (Bucket, bool)>,
}
impl Default for Capacity {
    fn default() -> Self {
        Self {
            global: Bucket::new(8.0),
            devices: HashMap::new(),
        }
    }
}
pub(super) struct Guard<'a> {
    capacity: &'a Mutex<Capacity>,
    device: String,
}
impl Drop for Guard<'_> {
    fn drop(&mut self) {
        if let Ok(mut c) = self.capacity.lock() {
            if let Some(v) = c.devices.get_mut(&self.device) {
                v.1 = false;
            }
        }
    }
}
fn limited() -> Error {
    let mut e = Error::new(429, "OFFLINE_INTAKE_CAPACITY");
    e.retry_after = Some(1);
    e
}
pub(super) fn begin<'a>(capacity: &'a Mutex<Capacity>, device: &str) -> Result<Guard<'a>> {
    let mut c = capacity.lock().map_err(|_| limited())?;
    c.devices
        .retain(|_, (b, active)| *active || b.last.elapsed().as_secs() < 60);
    if !c.devices.contains_key(device) && c.devices.len() >= 4096 {
        return Err(limited());
    }
    if !c.global.take(20.0, 8.0) {
        return Err(limited());
    }
    let v = c
        .devices
        .entry(device.into())
        .or_insert_with(|| (Bucket::new(2.0), false));
    if v.1 || !v.0.take(2.0, 2.0) {
        return Err(limited());
    }
    v.1 = true;
    Ok(Guard {
        capacity,
        device: device.into(),
    })
}
pub(super) fn disk(root: &std::path::Path) -> Result<()> {
    if fs2::available_space(root)? < 1024 * 1024 * 1024 {
        return Err(limited());
    }
    Ok(())
}
