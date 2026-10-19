//! Reuse the existing monthly/day readability contract through Host's normal dependency.
//! The standalone quote-excel test target also resolves unrelated calamine dev dependencies
//! absent from the offline cache. This target uses the same assertions without fetching them.
include!("../../quote-excel/tests/readable.rs");
