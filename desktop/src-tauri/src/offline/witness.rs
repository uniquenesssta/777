//! DPAPI high water survives an older SQLite copy; allocation gaps are intentional.
use super::*;
use std::{fs, io::Write};
impl Local {
    fn witness_value(&self) -> Result<Value> {
        if !self
            .witness
            .try_exists()
            .map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?
        {
            return Ok(json!({"clock":0,"sequences":{}}));
        }
        crate::journal::check(&self.witness)?;
        if fs::metadata(&self.witness)
            .map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?
            .len()
            > 1048576
        {
            return Err(fault("LOCAL_HIGH_WATER_UNAVAILABLE"));
        }
        self.decode(&fs::read(&self.witness).map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?)
    }
    pub(super) fn witness_clock(&self) -> Result<i64> {
        self.witness_value()?["clock"]
            .as_i64()
            .ok_or_else(|| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))
    }
    /// Call under the business database's BEGIN IMMEDIATE writer reservation.
    pub(super) fn checkpoint(&self, allocation: Option<(&str, i64)>, at: i64) -> Result<i64> {
        if self.c.is_autocommit() {
            return Err(fault("LOCAL_TRANSACTION_REQUIRED"));
        }
        let mut value = self.witness_value()?;
        value["clock"] = json!(at.max(value["clock"].as_i64().unwrap_or(at)));
        let mut sequence = 0;
        if let Some((stream, requested)) = allocation {
            sequence = requested.max(
                value["sequences"][stream]
                    .as_i64()
                    .unwrap_or(0)
                    .checked_add(1)
                    .ok_or_else(|| fault("LOCAL_VERSION_INVALID"))?,
            );
            value["sequences"][stream] = json!(sequence);
        }
        let temporary = self
            .witness
            .with_file_name(format!("offline-water-{}.tmp", crate::types::new_id()?));
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?;
        let result = (|| {
            file.write_all(&self.encode(&value)?)
                .and_then(|_| file.sync_all())
                .map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?;
            drop(file);
            fs::rename(&temporary, &self.witness)
                .map_err(|_| fault("LOCAL_HIGH_WATER_UNAVAILABLE"))?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(temporary);
        }
        result?;
        Ok(sequence)
    }
}
