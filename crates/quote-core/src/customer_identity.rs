//! Quote customer identity is field-specific and never derived from an order number.
use serde::{Deserialize, Serialize};
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CustomerIdentity {
    pub customer: String,
    pub wechat: String,
}
impl CustomerIdentity {
    pub fn valid(&self) -> bool {
        self.customer.chars().count() <= 256 && self.wechat.chars().count() <= 256
    }
    pub fn matches(&self, customer: &str, wechat: &str) -> bool {
        let name = self.customer.trim();
        let wx = self.wechat.trim();
        (!name.is_empty() && name == customer.trim()) || (!wx.is_empty() && wx == wechat.trim())
    }
}
