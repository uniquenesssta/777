//! A separate OS-backed SQLite lock releases immediately when a sync process dies.
use super::*;
impl Local {
    pub(crate) fn sync_guard(&self) -> Result<Option<rusqlite::Connection>> {
        for suffix in ["", "-wal", "-shm", "-journal"] {
            let path = self
                .transport
                .with_file_name(format!("offline-transport.sqlite3{suffix}"));
            if path
                .try_exists()
                .map_err(|_| fault("LOCAL_ORDERS_UNAVAILABLE"))?
            {
                crate::journal::check(&path)?;
            }
        }
        let c = rusqlite::Connection::open(&self.transport).map_err(sql)?;
        c.busy_timeout(std::time::Duration::ZERO).map_err(sql)?;
        match c.execute_batch("BEGIN EXCLUSIVE") {
            Ok(()) => Ok(Some(c)),
            Err(rusqlite::Error::SqliteFailure(e, _))
                if [
                    rusqlite::ErrorCode::DatabaseBusy,
                    rusqlite::ErrorCode::DatabaseLocked,
                ]
                .contains(&e.code) =>
            {
                Ok(None)
            }
            Err(e) => Err(sql(e)),
        }
    }
}
