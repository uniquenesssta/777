use serde::{Deserialize, Serialize};
use serde_json::Value;
#[derive(Debug, Clone, Serialize)]
pub struct DesktopError {
    pub code: String,
    pub status: u16,
}
pub type Result<T> = std::result::Result<T, DesktopError>;
impl DesktopError {
    pub fn new(status: u16, code: &str) -> Self {
        Self {
            status,
            code: code.into(),
        }
    }
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Connection {
    pub url: String,
    pub certificate_pem: String,
    pub certificate_sha256: String,
}
#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum Action {
    Connection {},
    Connect {
        connection: Connection,
        username: String,
        password: String,
    },
    Disconnect {},
    Prices {},
    Calculate {
        snapshot: Value,
        draft_revision: String,
    },
    Submit {
        snapshot: Value,
        details: Value,
        draft_revision: String,
    },
    Orders {
        q: String,
        state: String,
        offset: u32,
        view: String,
    },
    Order {
        order_id: String,
    },
    Note {
        order_id: String,
        expected_revision: String,
        body: String,
    },
    SetState {
        order_id: String,
        expected_revision: String,
        state: String,
        reason: String,
    },
    PublishPrices {
        prices: Value,
        expected_price_version_id: Option<String>,
    },
    Settings {},
    SaveSettings {
        revision: String,
        export_dir: String,
        image_dir: String,
    },
    Outputs {},
    CreateOutput {
        order_id: String,
        expected_revision: String,
        kind: String,
    },
    RetryOutput {
        job_id: String,
    },
    Recover {
        retry: bool,
    },
    BackupStatus {},
    Backup {},
}
pub fn revision(raw: &str) -> Result<i64> {
    let n = raw
        .parse::<i64>()
        .map_err(|_| DesktopError::new(422, "INVALID_REVISION"))?;
    if n < 1 || n.to_string() != raw {
        return Err(DesktopError::new(422, "INVALID_REVISION"));
    }
    Ok(n)
}
pub fn identifier(raw: &str) -> Result<&str> {
    let b = raw.as_bytes();
    if b.len() != 36
        || !b.iter().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                *c == b'-'
            } else {
                c.is_ascii_hexdigit() && !c.is_ascii_uppercase()
            }
        })
    {
        return Err(DesktopError::new(422, "INVALID_ID"));
    }
    Ok(raw)
}
pub fn new_id() -> Result<String> {
    let mut b = [0u8; 16];
    getrandom::getrandom(&mut b).map_err(|_| DesktopError::new(503, "RANDOM_UNAVAILABLE"))?;
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    let s = b.iter().map(|x| format!("{x:02x}")).collect::<String>();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..]
    ))
}
