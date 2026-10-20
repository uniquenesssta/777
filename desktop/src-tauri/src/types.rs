use serde::{Deserialize, Serialize};
use serde_json::Value;
#[derive(Debug, Clone, Serialize)]
pub struct DesktopError {
    pub code: String,
    pub status: u16,
    #[serde(skip)]
    pub retry_after: Option<u64>,
}
pub type Result<T> = std::result::Result<T, DesktopError>;
impl DesktopError {
    pub fn new(status: u16, code: &str) -> Self {
        quote_diagnostics::event(
            "desktop.error",
            serde_json::json!({"status":status,"code":code}),
        );
        Self {
            status,
            code: code.into(),
            retry_after: None,
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
    UiDiagnostic {
        event: UiEvent,
        order_id: Option<String>,
        revision: Option<String>,
        draft_revision: Option<String>,
        lines: Option<u16>,
        error_kind: Option<UiErrorKind>,
        source: Option<UiSource>,
        line: Option<u32>,
        column: Option<u32>,
    },
    #[cfg(all(
        debug_assertions,
        not(any(feature = "manager", feature = "sales", feature = "verification"))
    ))]
    Developer {
        request: crate::developer::DeveloperAction,
    },
    Bootstrap {},
    Connection {},
    Connect {
        connection: Connection,
        #[serde(default)]
        username: Option<String>,
        #[serde(default)]
        password: Option<String>,
    },
    Disconnect {},
    ImportConnection {
        path: String,
    },
    ImportEnrollment {
        path: String,
    },
    BusinessDirectory {},
    SaveBusinessDirectory {
        directory: String,
    },
    PackageTarget {},
    UseCurrentPackageTarget {},
    VerifyPackageTarget {
        connection: Connection,
        username: String,
        password: String,
    },
    Prices {},
    PricePreview {
        cost: String,
        k: String,
    },
    Calculate {
        snapshot: Value,
        draft_revision: String,
    },
    Submit {
        snapshot: Value,
        details: Value,
        draft_revision: String,
        #[serde(default)]
        operation_id: Option<String>,
    },
    CustomerOrders {
        query: String,
        offset: u32,
        group_id: Option<String>,
        order_offset: Option<u32>,
    },
    OrderPreview {
        snapshot: Value,
        sources: Value,
        order_id: Option<String>,
        expected_revision: Option<String>,
        draft_revision: String,
    },
    SaveOrder {
        snapshot: Value,
        sources: Value,
        order_id: Option<String>,
        expected_revision: Option<String>,
        draft_revision: String,
        details: Value,
        customer: Value,
        #[serde(default)]
        operation_id: Option<String>,
    },
    LocalReceipt {
        operation_id: String,
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
    OrderChanges {
        order_id: String,
        revision: String,
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
    Analytics {
        period: String,
        from: String,
        to: String,
    },
    PickDirectory {
        target: String,
    },
    Settings {},
    SaveSettings {
        revision: String,
        export_dir: String,
        image_dir: String,
    },
    Outputs {
        #[serde(default)]
        offset: u32,
    },
    OpenOutputFolder {
        job_id: String,
    },
    CreateReport {
        from: String,
        to: String,
    },
    CreateOutput {
        order_id: String,
        expected_revision: String,
        kind: String,
    },
    DeleteOutput {
        job_id: String,
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

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UiEvent {
    EditRequested,
    EditResumed,
    EditLoaded,
    DraftSwitchRequested,
    DraftSwitchConfirmed,
    DraftContinued,
    SaveRequested,
    SaveConfirmed,
    DraftContext,
    FrontendError,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UiErrorKind {
    TypeError,
    ReferenceError,
    RangeError,
    SyntaxError,
    Error,
    Unknown,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UiSource {
    Workbench,
    Draft,
    Quote,
    Detail,
    Application,
    Other,
}
impl Action {
    pub fn diagnostic_name(&self) -> &'static str {
        match self {
            Self::UiDiagnostic { .. } => "UiDiagnostic",
            #[cfg(all(
                debug_assertions,
                not(any(feature = "manager", feature = "sales", feature = "verification"))
            ))]
            Self::Developer { .. } => "Developer",
            Self::Bootstrap { .. } => "Bootstrap",
            Self::Connection { .. } => "Connection",
            Self::Connect { .. } => "Connect",
            Self::Disconnect { .. } => "Disconnect",
            Self::ImportConnection { .. } => "ImportConnection",
            Self::ImportEnrollment { .. } => "ImportEnrollment",
            Self::BusinessDirectory { .. } => "BusinessDirectory",
            Self::SaveBusinessDirectory { .. } => "SaveBusinessDirectory",
            Self::PackageTarget { .. } => "PackageTarget",
            Self::UseCurrentPackageTarget { .. } => "UseCurrentPackageTarget",
            Self::VerifyPackageTarget { .. } => "VerifyPackageTarget",
            Self::Prices { .. } => "Prices",
            Self::PricePreview { .. } => "PricePreview",
            Self::Calculate { .. } => "Calculate",
            Self::Submit { .. } => "Submit",
            Self::Orders { .. } => "Orders",
            Self::CustomerOrders { .. } => "CustomerOrders",
            Self::OrderPreview { .. } => "OrderPreview",
            Self::SaveOrder { .. } => "SaveOrder",
            Self::LocalReceipt { .. } => "LocalReceipt",
            Self::Order { .. } => "Order",
            Self::OrderChanges { .. } => "OrderChanges",
            Self::Note { .. } => "Note",
            Self::SetState { .. } => "SetState",
            Self::PublishPrices { .. } => "PublishPrices",
            Self::Analytics { .. } => "Analytics",
            Self::PickDirectory { .. } => "PickDirectory",
            Self::Settings { .. } => "Settings",
            Self::SaveSettings { .. } => "SaveSettings",
            Self::Outputs { .. } => "Outputs",
            Self::OpenOutputFolder { .. } => "OpenOutputFolder",
            Self::CreateReport { .. } => "CreateReport",
            Self::CreateOutput { .. } => "CreateOutput",
            Self::DeleteOutput { .. } => "DeleteOutput",
            Self::RetryOutput { .. } => "RetryOutput",
            Self::Recover { .. } => "Recover",
            Self::BackupStatus { .. } => "BackupStatus",
            Self::Backup { .. } => "Backup",
        }
    }
    /// Only operations that can persist a request or mutate business state
    /// coordinate close. A slow login/query must not trap the user in a window.
    pub fn protects_close(&self) -> bool {
        #[cfg(all(
            debug_assertions,
            not(any(feature = "manager", feature = "sales", feature = "verification"))
        ))]
        if let Self::Developer { request } = self {
            return request.protects_close();
        }
        matches!(
            self,
            Self::ImportEnrollment { .. }
                | Self::Submit { .. }
                | Self::Note { .. }
                | Self::SetState { .. }
                | Self::PublishPrices { .. }
                | Self::SaveSettings { .. }
                | Self::CreateReport { .. }
                | Self::CreateOutput { .. }
                | Self::SaveOrder { .. }
                | Self::DeleteOutput { .. }
                | Self::RetryOutput { .. }
                | Self::Recover { .. }
                | Self::Backup {}
        )
    }
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

#[cfg(test)]
mod close_tests {
    use super::*;
    #[test]
    fn ui_diagnostics_only_accept_known_events_and_metadata() {
        let mut value = serde_json::json!({"action":"ui_diagnostic","event":"frontend_error","error_kind":"type_error","source":"quote","line":12,"column":4});
        assert!(serde_json::from_value::<Action>(value.clone()).is_ok());
        value["message"] = serde_json::json!("customer/cost/body");
        assert!(serde_json::from_value::<Action>(value.clone()).is_err());
        value.as_object_mut().unwrap().remove("message");
        value["event"] = serde_json::json!("arbitrary-user-text");
        assert!(serde_json::from_value::<Action>(value).is_err());
    }
    #[test]
    fn readonly_network_and_calculation_do_not_protect_close() {
        assert!(!Action::Bootstrap {}.protects_close());
        assert!(!Action::Orders {
            q: "".into(),
            state: "".into(),
            offset: 0,
            view: "".into()
        }
        .protects_close());
        assert!(!Action::Calculate {
            snapshot: Value::Null,
            draft_revision: "1".into()
        }
        .protects_close());
    }
    #[test]
    fn writes_and_unknown_receipt_recovery_protect_close() {
        assert!(Action::Submit {
            operation_id: None,
            snapshot: Value::Null,
            details: Value::Null,
            draft_revision: "1".into()
        }
        .protects_close());
        assert!(Action::CreateOutput {
            order_id: "".into(),
            expected_revision: "1".into(),
            kind: "quote_png".into()
        }
        .protects_close());
        assert!(Action::Recover { retry: false }.protects_close());
        assert!(Action::Backup {}.protects_close());
    }
}
