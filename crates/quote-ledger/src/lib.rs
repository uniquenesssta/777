//! Native ledger-v1 storage. Authentication stays at the trusted service boundary.
pub mod integrity;
pub mod paths;
pub mod store;
use serde::Serialize;
#[derive(Debug, Serialize)]
pub struct Error {
    pub code: String,
}
impl Error {
    pub fn new(code: &str) -> Self {
        Self { code: code.into() }
    }
}
impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        use rusqlite::ErrorCode;
        Self::new(match e {
            rusqlite::Error::SqliteFailure(ref e, _)
                if [ErrorCode::DatabaseBusy, ErrorCode::DatabaseLocked].contains(&e.code) =>
            {
                "BUSY"
            }
            rusqlite::Error::SqliteFailure(ref e, _)
                if e.code == ErrorCode::ConstraintViolation =>
            {
                "VALIDATION"
            }
            _ => "INVALID_DATABASE",
        })
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::new("INVALID_DATABASE")
    }
}
pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn frozen_schema_hash_matches_native_sqlite_metadata() {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(store::DDL).unwrap();
        assert_eq!(store::schema_hash(&c).unwrap(), store::SCHEMA_HASH);
    }
    #[test]
    fn generated_identifiers_are_canonical_and_distinct() {
        let a = store::uid().unwrap();
        let b = store::uid().unwrap();
        store::id(&a).unwrap();
        assert_ne!(a, b);
        assert!(store::id(&a.to_uppercase()).is_err());
    }
    #[test]
    fn native_principal_requires_known_role_and_bounded_identity() {
        assert!(store::Actor {
            subject: "sales".into(),
            role: "admin-claimed".into()
        }
        .check()
        .is_err());
        assert!(store::Actor {
            subject: "sales".into(),
            role: "sales".into()
        }
        .admin()
        .is_err());
        assert!(store::Actor {
            subject: "".into(),
            role: "admin".into()
        }
        .check()
        .is_err());
    }
    #[test]
    fn version_or_extra_trigger_is_not_repaired() {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(store::DDL).unwrap();
        assert!(store::verify(&c).is_err());
        c.execute_batch("CREATE TRIGGER foreign_trigger AFTER INSERT ON notes BEGIN SELECT 1; END")
            .unwrap();
        assert_ne!(store::schema_hash(&c).unwrap(), store::SCHEMA_HASH);
    }
}
