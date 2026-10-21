//! Bounded lossless JSON reader. Keeps number lexemes and rejects duplicate keys.
use crate::{
    models::*,
    numbers::{parse_number, trim},
};
use serde_json::{json, Value};
use std::collections::HashSet;
#[derive(Clone, Debug, PartialEq, Eq)]
struct Text {
    value: String,
    valid: bool,
}
#[derive(Clone, Debug)]
enum Node {
    Text(Text),
    Number(String),
    Bool(bool),
    Null,
    Array(Vec<Node>),
    Object(Vec<(Text, Node)>),
}
struct Reader<'a> {
    s: &'a str,
    i: usize,
}
fn json_fault(reason: &str) -> Fault {
    Fault::new(reason, "json")
}
impl<'a> Reader<'a> {
    fn white(&mut self) {
        while self.i < self.s.len() && b" \r\n\t".contains(&self.s.as_bytes()[self.i]) {
            self.i += 1;
        }
    }
    fn take(&mut self, b: u8) -> bool {
        self.white();
        if self.s.as_bytes().get(self.i) == Some(&b) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn string(&mut self) -> Result<Text, Fault> {
        if !self.take(b'"') {
            return Err(json_fault("JSON_SYNTAX"));
        }
        let mut value = String::new();
        let mut valid = true;
        while self.i < self.s.len() {
            let c = self.s[self.i..].chars().next().unwrap();
            self.i += c.len_utf8();
            match c {
                '"' => return Ok(Text { value, valid }),
                '\\' => {
                    let b = *self
                        .s
                        .as_bytes()
                        .get(self.i)
                        .ok_or_else(|| json_fault("JSON_SYNTAX"))?;
                    self.i += 1;
                    match b {
                        b'"' => value.push('"'),
                        b'\\' => value.push('\\'),
                        b'/' => value.push('/'),
                        b'b' => value.push('\u{8}'),
                        b'f' => value.push('\u{c}'),
                        b'n' => value.push('\n'),
                        b'r' => value.push('\r'),
                        b't' => value.push('\t'),
                        b'u' => {
                            let first = self.hex()?;
                            let code = if (0xd800..=0xdbff).contains(&first)
                                && self.s[self.i..].starts_with("\\u")
                            {
                                let saved = self.i;
                                self.i += 2;
                                let second = self.hex()?;
                                if (0xdc00..=0xdfff).contains(&second) {
                                    0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00)
                                } else {
                                    self.i = saved;
                                    first
                                }
                            } else {
                                first
                            };
                            if let Some(c) = char::from_u32(code) {
                                value.push(c);
                            } else {
                                valid = false;
                                value.push('\u{fffd}');
                            }
                        }
                        _ => return Err(json_fault("JSON_SYNTAX")),
                    }
                }
                c if (c as u32) < 32 => return Err(json_fault("JSON_SYNTAX")),
                _ => value.push(c),
            }
        }
        Err(json_fault("JSON_SYNTAX"))
    }
    fn hex(&mut self) -> Result<u32, Fault> {
        let mut n = 0;
        for _ in 0..4 {
            let b = *self
                .s
                .as_bytes()
                .get(self.i)
                .ok_or_else(|| json_fault("JSON_SYNTAX"))?;
            self.i += 1;
            let x = (b as char)
                .to_digit(16)
                .ok_or_else(|| json_fault("JSON_SYNTAX"))?;
            n = n * 16 + x;
        }
        Ok(n)
    }
    fn node(&mut self, depth: usize) -> Result<Node, Fault> {
        self.white();
        let b = *self
            .s
            .as_bytes()
            .get(self.i)
            .ok_or_else(|| json_fault("JSON_SYNTAX"))?;
        if depth > 32 {
            return Err(json_fault("JSON_DEPTH_CAPACITY"));
        }
        if b == b'"' {
            return Ok(Node::Text(self.string()?));
        }
        if b == b'[' {
            self.i += 1;
            let mut a = vec![];
            if self.take(b']') {
                return Ok(Node::Array(a));
            }
            loop {
                a.push(self.node(depth + 1)?);
                if self.take(b']') {
                    break;
                }
                if !self.take(b',') {
                    return Err(json_fault("JSON_SYNTAX"));
                }
            }
            return Ok(Node::Array(a));
        }
        if b == b'{' {
            self.i += 1;
            let mut a = vec![];
            if self.take(b'}') {
                return Ok(Node::Object(a));
            }
            loop {
                let key = self.string()?;
                if !self.take(b':') {
                    return Err(json_fault("JSON_SYNTAX"));
                }
                a.push((key, self.node(depth + 1)?));
                if self.take(b'}') {
                    break;
                }
                if !self.take(b',') {
                    return Err(json_fault("JSON_SYNTAX"));
                }
            }
            let mut keys = HashSet::new();
            if a.iter()
                .any(|(t, _)| !keys.insert((t.value.clone(), t.valid)))
            {
                return Err(json_fault("JSON_DUPLICATE_KEY"));
            }
            return Ok(Node::Object(a));
        }
        for (s, n) in [
            ("true", Node::Bool(true)),
            ("false", Node::Bool(false)),
            ("null", Node::Null),
        ] {
            if self.s[self.i..].starts_with(s) {
                self.i += s.len();
                return Ok(n);
            }
        }
        if ["NaN", "Infinity", "-Infinity"]
            .iter()
            .any(|s| self.s[self.i..].starts_with(s))
        {
            return Err(json_fault("JSON_NON_FINITE"));
        }
        let start = self.i;
        if b == b'-' {
            self.i += 1;
        }
        let digits = self.i;
        if self.s.as_bytes().get(self.i) == Some(&b'0') {
            self.i += 1;
        } else {
            while self
                .s
                .as_bytes()
                .get(self.i)
                .is_some_and(u8::is_ascii_digit)
            {
                self.i += 1;
            }
        }
        if digits == self.i {
            return Err(json_fault("JSON_SYNTAX"));
        }
        if self.s.as_bytes().get(self.i) == Some(&b'.') {
            self.i += 1;
            let start = self.i;
            while self
                .s
                .as_bytes()
                .get(self.i)
                .is_some_and(u8::is_ascii_digit)
            {
                self.i += 1;
            }
            if start == self.i {
                return Err(json_fault("JSON_SYNTAX"));
            }
        }
        if self
            .s
            .as_bytes()
            .get(self.i)
            .is_some_and(|b| *b == b'e' || *b == b'E')
        {
            self.i += 1;
            if self
                .s
                .as_bytes()
                .get(self.i)
                .is_some_and(|b| *b == b'+' || *b == b'-')
            {
                self.i += 1;
            }
            let start = self.i;
            while self
                .s
                .as_bytes()
                .get(self.i)
                .is_some_and(u8::is_ascii_digit)
            {
                self.i += 1;
            }
            if start == self.i {
                return Err(json_fault("JSON_SYNTAX"));
            }
        }
        let token = &self.s[start..self.i];
        if token.len() > 256 {
            return Err(json_fault("JSON_NUMBER_CAPACITY"));
        }
        Ok(Node::Number(token.into()))
    }
}
fn depth_check(s: &str) -> Result<(), Fault> {
    let (mut depth, mut string, mut escaped) = (0i32, false, false);
    for c in s.chars() {
        if string {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                string = false;
            }
        } else if c == '"' {
            string = true;
        } else if c == '[' || c == '{' {
            depth += 1;
            if depth > 32 {
                return Err(json_fault("JSON_DEPTH_CAPACITY"));
            }
        } else if c == ']' || c == '}' {
            depth -= 1;
        }
    }
    Ok(())
}
fn get<'a>(o: &'a [(Text, Node)], key: &str) -> Option<&'a Node> {
    o.iter()
        .find(|(k, _)| k.valid && k.value == key)
        .map(|(_, n)| n)
}
fn text(n: Option<&Node>, field: &str, limit: usize) -> Result<String, Fault> {
    let Some(Node::Text(t)) = n else {
        return Err(Fault::new("CONFIG_TEXT_TYPE_OR_CAPACITY", field));
    };
    if t.value.chars().count() > limit {
        return Err(Fault::new("CONFIG_TEXT_TYPE_OR_CAPACITY", field));
    }
    if !t.valid {
        return Err(Fault::new("CONFIG_TEXT_ENCODING", field));
    }
    if t.value.chars().any(|c| (c as u32) < 32) {
        return Err(Fault::new("CONFIG_TEXT_CONTROL", field));
    }
    Ok(t.value.clone())
}
fn name(n: Option<&Node>, field: &str) -> Result<String, Fault> {
    let s = text(n, field, 256)?;
    let s = trim(&s);
    if s.is_empty() {
        Err(Fault::new("PRODUCT_NAME_EMPTY", field))
    } else if s == "折扣" {
        Err(Fault::new("PRODUCT_NAME_RESERVED", field))
    } else {
        Ok(s.into())
    }
}
fn price(n: Option<&Node>, field: &str, empty: bool) -> Result<String, Fault> {
    let s = match n {
        Some(Node::Text(t)) if t.valid => t.value.clone(),
        Some(Node::Number(s)) => s.clone(),
        None if empty => String::new(),
        _ => return Err(Fault::new("CONFIG_NUMBER_TYPE", field)),
    };
    parse_number(&json!(s), field, empty)?;
    Ok(s)
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Config {
    pub prices: Prices,
    pub source_schema: String,
    pub export_dir: Option<String>,
    pub original_json: String,
    pub screenshot_dir: Option<String>,
}
impl Config {
    pub fn wire(&self) -> Value {
        json!({"prices":self.prices,"source_schema":self.source_schema,"export_dir":self.export_dir,"original_json":self.original_json,"screenshot_dir":self.screenshot_dir})
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConfigResult {
    pub status: String,
    pub config: Option<Config>,
    pub issues: Vec<Issue>,
}
impl ConfigResult {
    pub fn wire(&self) -> Value {
        json!({"status":self.status,"config":self.config.as_ref().map(Config::wire),"issues":self.issues})
    }
}
pub enum Source<'a> {
    Text(&'a str),
    Bytes(&'a [u8]),
    Invalid,
}
pub fn parse_config(source: Source<'_>, version: &Value, legacy: Option<&Value>) -> ConfigResult {
    match parse_checked(source, version, legacy) {
        Ok(r) => r,
        Err(f) => ConfigResult {
            status: "VALIDATION".into(),
            config: None,
            issues: vec![Issue::validation(f, None)],
        },
    }
}
fn parse_checked(
    source: Source<'_>,
    version: &Value,
    legacy: Option<&Value>,
) -> Result<ConfigResult, Fault> {
    let v = version
        .as_str()
        .ok_or_else(|| Fault::new("CONFIG_TEXT_TYPE_OR_CAPACITY", "price_version_id"))?;
    let v = text(
        Some(&Node::Text(Text {
            value: v.into(),
            valid: true,
        })),
        "price_version_id",
        256,
    )?;
    if v.is_empty() || v != trim(&v) {
        return Err(Fault::new("PRICE_VERSION_ID", "price_version_id"));
    }
    let original = match source {
        Source::Text(s) => s,
        Source::Bytes(b) => {
            if b.len() > 1048576 {
                return Err(json_fault("JSON_BYTE_CAPACITY"));
            }
            std::str::from_utf8(b).map_err(|_| json_fault("JSON_ENCODING"))?
        }
        Source::Invalid => return Err(json_fault("JSON_SOURCE_TYPE")),
    };
    if original.len() > 1048576 {
        return Err(json_fault("JSON_BYTE_CAPACITY"));
    }
    let s = original.strip_prefix('\u{feff}').unwrap_or(original);
    depth_check(s)?;
    let mut reader = Reader { s, i: 0 };
    let n = reader.node(0)?;
    reader.white();
    if reader.i != s.len() {
        return Err(json_fault("JSON_SYNTAX"));
    }
    let Node::Object(o) = n else {
        return Err(json_fault("CONFIG_ROOT_TYPE"));
    };
    let mut issues = vec![];
    let (mut export_dir, mut screenshot_dir) = (None, None);
    for (f, d) in [
        ("export_dir", &mut export_dir),
        ("screenshot_dir", &mut screenshot_dir),
    ] {
        if let Some(n) = get(&o, f) {
            match text(Some(n), f, 32767) {
                Ok(s) => *d = Some(s),
                Err(e) => issues.push(Issue::validation(e, None)),
            }
        }
    }
    let modern = get(&o, "items").is_some();
    let mut policies = HashSet::new();
    let mut entries = vec![];
    if modern {
        for (k, _) in &o {
            if !["items", "export_dir", "screenshot_dir"].contains(&k.value.as_str()) {
                issues.push(Issue::validation(
                    Fault::new("CONFIG_UNKNOWN_FIELD", &k.value),
                    None,
                ));
            }
        }
        let Some(Node::Array(items)) = get(&o, "items") else {
            return Err(Fault::new("CONFIG_ITEMS_TYPE", "items"));
        };
        entries.extend(items.iter().cloned());
    } else {
        for (k, n) in &o {
            if !["export_dir", "screenshot_dir"].contains(&k.value.as_str()) {
                entries.push(Node::Array(vec![Node::Text(k.clone()), n.clone()]));
            }
        }
        if !entries.is_empty() {
            let policy = legacy.and_then(Value::as_array).ok_or_else(|| {
                Fault::new("LEGACY_SINGLE_POLICY_REQUIRED", "legacy_single_names")
            })?;
            if policy.len() > 10000 {
                return Err(Fault::new("CONFIG_PRODUCT_CAPACITY", "legacy_single_names"));
            }
            for p in policy {
                let n = p.as_str().map(|s| {
                    Node::Text(Text {
                        value: s.into(),
                        valid: true,
                    })
                });
                policies.insert(name(n.as_ref(), "legacy_single_names")?);
            }
        }
    }
    // An explicit empty catalog is a valid publication; an empty legacy object is not.
    if (!modern && entries.is_empty()) || entries.len() > 10000 {
        return Err(Fault::new("CONFIG_PRODUCT_CAPACITY", "items"));
    }
    let mut seen = HashSet::new();
    let mut items = vec![];
    for (i, entry) in entries.iter().enumerate() {
        let base = format!("{}[{i}]", if modern { "items" } else { "legacy" });
        let mut item = || -> Result<PriceItem, Fault> {
            let object = if modern {
                if let Node::Object(o) = entry {
                    o.clone()
                } else {
                    return Err(Fault::new("CONFIG_ITEM_TYPE", &base));
                }
            } else {
                let Node::Array(e) = entry else {
                    unreachable!()
                };
                let Node::Array(values) = &e[1] else {
                    return Err(Fault::new("LEGACY_PRICE_SHAPE", &base));
                };
                if values.len() != 3 {
                    return Err(Fault::new("LEGACY_PRICE_SHAPE", &base));
                }
                ["sale", "cost", "k"]
                    .iter()
                    .zip(values)
                    .map(|(k, n)| {
                        (
                            Text {
                                value: (*k).into(),
                                valid: true,
                            },
                            n.clone(),
                        )
                    })
                    .chain(std::iter::once((
                        Text {
                            value: "name".into(),
                            valid: true,
                        },
                        e[0].clone(),
                    )))
                    .collect()
            };
            for (k, _) in &object {
                if ![
                    "name",
                    "sale",
                    "cost",
                    "k",
                    "single",
                    "qty_only",
                    "pricing_mode",
                    "discount_eligible",
                ]
                .contains(&k.value.as_str())
                {
                    issues.push(Issue::validation(
                        Fault::new("CONFIG_UNKNOWN_FIELD", &format!("{base}.{}", k.value)),
                        None,
                    ));
                }
            }
            let name = name(get(&object, "name"), &format!("{base}.name"))?;
            if !seen.insert(name.clone()) {
                return Err(Fault::new(
                    "PRODUCT_NAME_DUPLICATE",
                    &format!("{base}.name"),
                ));
            }
            let mut flags = vec![];
            for flag in ["single", "qty_only"] {
                if let Some(n) = get(&object, flag) {
                    let Node::Bool(b) = n else {
                        return Err(Fault::new("SINGLE_NOT_BOOLEAN", &format!("{base}.{flag}")));
                    };
                    flags.push(*b);
                }
            }
            if flags.len() == 2 && flags[0] != flags[1] {
                return Err(Fault::new(
                    "SINGLE_FLAGS_CONFLICT",
                    &format!("{base}.single"),
                ));
            }
            let single = if modern {
                flags.first().copied().unwrap_or(false)
            } else {
                policies.contains(&name)
            };
            let pricing_mode = if let Some(raw) = get(&object, "pricing_mode") {
                let mode = text(Some(raw), &format!("{base}.pricing_mode"), 32)?;
                Some(match mode.as_str() {
                    "manual" => crate::models::PricingMode::Manual,
                    "cost_plus" => crate::models::PricingMode::CostPlus,
                    _ => {
                        return Err(Fault::new(
                            "PRICING_MODE_INVALID",
                            &format!("{base}.pricing_mode"),
                        ))
                    }
                })
            } else {
                None
            };
            let discount_eligible = match get(&object, "discount_eligible") {
                None => None,
                Some(Node::Bool(value)) => Some(*value),
                Some(_) => {
                    return Err(Fault::new(
                        "DISCOUNT_ELIGIBLE_NOT_BOOLEAN",
                        &format!("{base}.discount_eligible"),
                    ))
                }
            };
            let mut item = PriceItem {
                product_id: json!(name),
                sale: if pricing_mode == Some(crate::models::PricingMode::CostPlus) {
                    json!("")
                } else {
                    json!(price(get(&object, "sale"), &format!("{base}.sale"), false)?)
                },
                cost: json!(price(get(&object, "cost"), &format!("{base}.cost"), false)?),
                k: json!(price(get(&object, "k"), &format!("{base}.k"), true)?),
                single: json!(single),
                discount_eligible,
                pricing_mode,
            };
            if item.pricing_mode.is_some() {
                let sale = crate::pricing::unit_sale(&item)?;
                if item.pricing_mode == Some(crate::models::PricingMode::CostPlus) {
                    item.sale = json!(sale.text());
                }
            }
            Ok(item)
        };
        match item() {
            Ok(item) => items.push(item),
            Err(e) => issues.push(Issue::validation(e, None)),
        }
    }
    if !issues.is_empty() {
        return Ok(ConfigResult {
            status: "VALIDATION".into(),
            config: None,
            issues,
        });
    }
    Ok(ConfigResult {
        status: "ok".into(),
        config: Some(Config {
            prices: Prices {
                price_version_id: json!(v),
                items,
            },
            source_schema: if modern {
                "json_items"
            } else {
                "json_legacy_price_dict"
            }
            .into(),
            export_dir,
            original_json: original.into(),
            screenshot_dir,
        }),
        issues: vec![],
    })
}
pub fn refresh_config(
    previous: Option<Config>,
    validation: ConfigResult,
) -> (Option<Config>, ConfigResult) {
    let active = validation.config.clone().or(previous);
    (active, validation)
}
