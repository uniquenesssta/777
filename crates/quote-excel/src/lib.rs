//! Bounded read-only OOXML evidence and newly created 777-output-v1 reports.
//! No existing workbook editor, formula engine, or financial calculator.
pub mod backup;
pub mod read;
pub mod write;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;
use serde_json::{json, Value};

pub const SOURCE_LIMIT: usize = 20 * 1024 * 1024;
pub const EXPANDED_LIMIT: u64 = 64 * 1024 * 1024;
pub const ROW_LIMIT: u32 = 50_000;
pub const CELL_LIMIT: usize = 1_000_000;
pub const OUTPUT_LIMIT: usize = 4 * 1024 * 1024;
#[derive(Debug, Clone, Serialize)]
pub struct Error {
    pub code: String,
    pub sheet: String,
    pub cell: String,
}
impl Error {
    pub fn new(code: &str) -> Self {
        Self {
            code: code.into(),
            sheet: String::new(),
            cell: String::new(),
        }
    }
    pub fn at(mut self, sheet: &str, cell: &str) -> Self {
        self.sheet = sheet.into();
        self.cell = cell.into();
        self
    }
}
pub type Result<T> = std::result::Result<T, Error>;
/// Trusted private DTO boundary. Does not access the ledger or arbitrary paths.
pub fn dispatch(input: &Value) -> Value {
    let result = match input["op"].as_str() {
        Some("xlsx_read") => input["data_base64"]
            .as_str()
            .ok_or_else(|| Error::new("SOURCE_TYPE_OR_SIZE_LIMIT"))
            .and_then(|s| {
                if s.len() > SOURCE_LIMIT.div_ceil(3) * 4 {
                    return Err(Error::new("SOURCE_TYPE_OR_SIZE_LIMIT"));
                }
                STANDARD
                    .decode(s)
                    .map_err(|_| Error::new("SOURCE_BASE64_INVALID"))
            })
            .and_then(|raw| read::read(&raw))
            .and_then(|book| {
                serde_json::to_value(book).map_err(|_| Error::new("FORMAT_DTO_INVALID"))
            }),
        Some("xlsx_write") => write::write(&input["payload"])
            .map(|bytes| json!({"data_base64":STANDARD.encode(bytes)})),
        _ => Err(Error::new("FORMAT_OPERATION_UNSUPPORTED")),
    };
    match result {
        Ok(v) => json!({"status":"ok","value":v}),
        Err(e) => json!({"status":"review_required","error":e}),
    }
}
