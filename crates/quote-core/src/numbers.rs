//! Exact coefficient/scale arithmetic; never convert financial values to float.
use crate::models::Fault;
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{Signed, ToPrimitive, Zero};
use serde_json::Value;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decimal {
    coefficient: BigInt,
    scale: u32,
}
fn ten(n: u32) -> BigInt {
    BigInt::from(10u8).pow(n)
}
impl Decimal {
    pub fn new(mut coefficient: BigInt, mut scale: u32) -> Self {
        if coefficient.is_zero() {
            scale = 0;
        } else {
            while scale > 0 && (&coefficient % 10u8).is_zero() {
                coefficient /= 10u8;
                scale -= 1;
            }
        }
        Self { coefficient, scale }
    }
    pub fn integer(n: impl Into<BigInt>) -> Self {
        Self::new(n.into(), 0)
    }
    pub fn cents(n: i64) -> Self {
        Self::new(n.into(), 2)
    }
    pub fn text(&self) -> String {
        let mut s = self.coefficient.abs().to_string();
        if self.scale > 0 {
            let n = self.scale as usize;
            if s.len() <= n {
                s = format!("{}{}", "0".repeat(n + 1 - s.len()), s);
            }
            s.insert(s.len() - n, '.');
        }
        if self.coefficient.is_negative() {
            s.insert(0, '-');
        }
        s
    }
    pub fn is_zero(&self) -> bool {
        self.coefficient.is_zero()
    }
    fn aligned(&self, other: &Self) -> (BigInt, BigInt, u32) {
        let scale = self.scale.max(other.scale);
        (
            &self.coefficient * ten(scale - self.scale),
            &other.coefficient * ten(scale - other.scale),
            scale,
        )
    }
    pub fn add(&self, other: &Self) -> Self {
        let (a, b, s) = self.aligned(other);
        Self::new(a + b, s)
    }
    pub fn sub(&self, other: &Self) -> Self {
        let (a, b, s) = self.aligned(other);
        Self::new(a - b, s)
    }
    pub fn mul(&self, other: &Self) -> Self {
        Self::new(
            &self.coefficient * &other.coefficient,
            self.scale + other.scale,
        )
    }
    pub fn negate(&self) -> Self {
        Self::new(-&self.coefficient, self.scale)
    }
    pub fn checked(self) -> Result<Self, Fault> {
        if self.scale > 60 || self.coefficient.abs() > ten(45 + self.scale) {
            Err(Fault::new("INTERMEDIATE_CAPACITY", ""))
        } else {
            Ok(self)
        }
    }
    fn ratio(&self, other: &Self) -> (BigInt, BigInt) {
        (
            &self.coefficient * ten(other.scale),
            &other.coefficient * ten(self.scale),
        )
    }
    pub fn divide(&self, other: &Self) -> Result<Self, Fault> {
        let (n, d) = self.ratio(other);
        Self::new(rounded_ratio(n, d, 12)?, 12).checked()
    }
    pub fn remainder(&self, other: &Self) -> Result<Self, Fault> {
        let (n, d) = self.ratio(other);
        if d.is_zero() {
            return Err(Fault::new("DIVISION_BY_ZERO", ""));
        }
        self.sub(&other.mul(&Self::integer(n.div_floor(&d))))
            .checked()
    }
    pub fn settle(&self) -> Result<i64, Fault> {
        let n = rounded_ratio(self.coefficient.clone(), ten(self.scale), 2)?;
        if n.abs() > BigInt::from(i64::MAX) {
            return Err(Fault::new("MONEY_CAPACITY", "amounts"));
        }
        n.to_i64()
            .ok_or_else(|| Fault::new("MONEY_CAPACITY", "amounts"))
    }
    fn field_ok(&self) -> bool {
        self.coefficient >= BigInt::zero() && self.coefficient <= ten(9 + self.scale)
    }
    fn literal(token: &str) -> Result<Self, Fault> {
        if !token
            .as_bytes()
            .first()
            .is_some_and(|b| b.is_ascii_digit() || *b == b'.')
        {
            return Err(Fault::new("LITERAL", ""));
        }
        let mut parts = token.split(['e', 'E']);
        let mantissa = parts.next().unwrap_or("");
        let exponent = if let Some(exp) = parts.next() {
            exp.parse::<i32>()
                .map_err(|_| Fault::new("LITERAL_EXPONENT", ""))?
        } else {
            0
        };
        if !(-12..=9).contains(&exponent) {
            return Err(Fault::new("LITERAL_EXPONENT", ""));
        }
        let dots = mantissa.bytes().filter(|b| *b == b'.').count();
        if dots > 1
            || !mantissa.bytes().all(|b| b.is_ascii_digit() || b == b'.')
            || !mantissa.bytes().any(|b| b.is_ascii_digit())
        {
            return Err(Fault::new("LITERAL", ""));
        }
        let fractional = mantissa.split_once('.').map_or(0, |(_, f)| f.len() as i32);
        let coefficient = BigInt::parse_bytes(mantissa.replace('.', "").as_bytes(), 10)
            .ok_or_else(|| Fault::new("LITERAL", ""))?;
        let scale = fractional - exponent;
        let value = if scale < 0 {
            Self::new(coefficient * ten((-scale) as u32), 0)
        } else {
            Self::new(coefficient, scale as u32)
        };
        if !value.field_ok() || value.scale > 12 {
            Err(Fault::new("LITERAL_CAPACITY", ""))
        } else {
            Ok(value)
        }
    }
}
pub fn rounded_ratio(
    mut numerator: BigInt,
    mut denominator: BigInt,
    scale: u32,
) -> Result<BigInt, Fault> {
    if denominator.is_zero() {
        return Err(Fault::new("DIVISION_BY_ZERO", ""));
    }
    if denominator.is_negative() {
        numerator = -numerator;
        denominator = -denominator;
    }
    let (q, r) = (numerator.abs() * ten(scale)).div_rem(&denominator);
    let q = q + BigInt::from(u8::from(r * 2u8 >= denominator));
    Ok(if numerator.is_negative() { -q } else { q })
}
pub fn py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
pub fn trim(s: &str) -> &str {
    s.trim_matches(py_space)
}
pub fn normalize(raw: &str) -> String {
    let mut s = raw.to_owned();
    for (a, b) in [
        ("，", ","),
        ("％", "%"),
        ("×", "*"),
        ("x", "*"),
        ("X", "*"),
        ("÷", "/"),
        ("（", "("),
        ("）", ")"),
        ("人民币", ""),
    ] {
        s = s.replace(a, b);
    }
    for unit in [
        "￥", "¥", "元", "块", "米", "m", "M", "个", "件", "张", "套", "倍", " ", ",",
    ] {
        s = s.replace(unit, "");
    }
    let c: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < c.len() {
        let prev_word = i > 0 && (c[i - 1].is_alphanumeric() || c[i - 1] == '_' || c[i - 1] == '.');
        if c[i].is_ascii_digit() && !prev_word {
            let start = i;
            while i < c.len() && c[i].is_ascii_digit() {
                i += 1;
            }
            if i + 1 < c.len() && c[i] == '.' && c[i + 1].is_ascii_digit() {
                i += 1;
                while i < c.len() && c[i].is_ascii_digit() {
                    i += 1;
                }
            }
            let token: String = c[start..i].iter().collect();
            if i < c.len() && c[i] == '%' {
                out.push_str(&format!("({token}/100)"));
                i += 1;
            } else {
                out.push_str(&token);
            }
        } else {
            out.push(c[i]);
            i += 1;
        }
    }
    out
}

#[derive(Debug)]
enum Expr {
    Literal(String),
    Unary(char, Box<Expr>),
    Binary(String, Box<Expr>, Box<Expr>),
    Unsupported(usize),
}
impl Expr {
    fn count(&self) -> usize {
        match self {
            Self::Literal(_) => 1,
            Self::Unary(_, a) => 2 + a.count(),
            Self::Binary(_, a, b) => 2 + a.count() + b.count(),
            Self::Unsupported(n) => *n,
        }
    }
    fn eval(&self, depth: usize) -> Result<Decimal, Fault> {
        if depth > 16 {
            return Err(Fault::new("AST_DEPTH", ""));
        }
        match self {
            Self::Literal(s) => Decimal::literal(s),
            Self::Unary(op, a) => {
                let n = a.eval(depth + 1)?;
                if *op == '-' {
                    n.negate().checked()
                } else {
                    n.checked()
                }
            }
            Self::Binary(op, a, b) => {
                if !["+", "-", "*", "/", "%"].contains(&op.as_str()) {
                    return Err(Fault::new("UNSUPPORTED_NODE", ""));
                }
                let a = a.eval(depth + 1)?;
                let b = b.eval(depth + 1)?;
                match op.as_str() {
                    "+" => a.add(&b).checked(),
                    "-" => a.sub(&b).checked(),
                    "*" => a.mul(&b).checked(),
                    "/" => a.divide(&b),
                    "%" => a.remainder(&b),
                    _ => unreachable!(),
                }
            }
            Self::Unsupported(_) => Err(Fault::new("UNSUPPORTED_NODE", "")),
        }
    }
}
#[derive(Clone, Debug, PartialEq)]
enum Token {
    Number(String),
    Name(String),
    Quoted,
    Op(String),
    Open,
    Close,
    End,
}
struct Parser {
    tokens: Vec<Token>,
    pos: usize,
}
fn syntax() -> Fault {
    Fault::new("SYNTAX", "")
}
impl Parser {
    fn new(s: &str) -> Result<Self, Fault> {
        let bytes = s.as_bytes();
        let mut i = 0;
        let mut tokens = vec![];
        let mut nesting = 0;
        while i < bytes.len() {
            let b = bytes[i];
            if b == b'#' {
                while i < bytes.len() && bytes[i] != b'\n' && bytes[i] != b'\r' {
                    i += 1;
                }
                continue;
            }
            if b == b'\\' && bytes.get(i + 1) == Some(&b'\n') {
                i += 2;
                continue;
            }
            if b == b'\\' && bytes.get(i + 1) == Some(&b'\r') && bytes.get(i + 2) == Some(&b'\n') {
                i += 3;
                continue;
            }
            if b.is_ascii_whitespace() {
                if nesting == 0 && (tokens.is_empty() || b == b'\n' || b == b'\r') {
                    return Err(syntax());
                }
                i += 1;
                continue;
            }
            if b.is_ascii_digit()
                || b == b'.' && i + 1 < bytes.len() && bytes[i + 1].is_ascii_digit()
            {
                let start = i;
                i += 1;
                while i < bytes.len()
                    && (bytes[i].is_ascii_digit() || bytes[i] == b'.' || bytes[i] == b'_')
                {
                    i += 1;
                }
                if i < bytes.len() && (bytes[i] == b'e' || bytes[i] == b'E') {
                    i += 1;
                    if i < bytes.len() && (bytes[i] == b'+' || bytes[i] == b'-') {
                        i += 1;
                    }
                    let exp_start = i;
                    while i < bytes.len() && (bytes[i].is_ascii_digit() || bytes[i] == b'_') {
                        i += 1;
                    }
                    if i == exp_start {
                        return Err(syntax());
                    }
                }
                let token = &s[start..i];
                if token.bytes().filter(|b| *b == b'.').count() > 1 {
                    return Err(syntax());
                }
                if !token.contains(['.', 'e', 'E', '_'])
                    && token.len() > 1
                    && token.starts_with('0')
                    && token.bytes().any(|b| b != b'0')
                {
                    return Err(syntax());
                }
                tokens.push(Token::Number(token.to_owned()));
                continue;
            }
            if b.is_ascii_alphabetic() || b == b'_' {
                let start = i;
                i += 1;
                while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                    i += 1;
                }
                tokens.push(Token::Name(s[start..i].into()));
                continue;
            }
            if b == b'\'' || b == b'"' {
                let quote = b;
                i += 1;
                while i < bytes.len() && bytes[i] != quote {
                    if bytes[i] == b'\\' {
                        i += 1;
                    }
                    i += 1;
                }
                if i >= bytes.len() {
                    return Err(syntax());
                }
                i += 1;
                tokens.push(Token::Quoted);
                continue;
            }
            match b {
                b'(' => {
                    tokens.push(Token::Open);
                    nesting += 1;
                }
                b')' => {
                    tokens.push(Token::Close);
                    nesting -= 1;
                    if nesting < 0 {
                        return Err(syntax());
                    }
                }
                b'+' | b'-' | b'*' | b'/' | b'%' | b'<' | b'>' | b'|' | b'&' | b'^' => {
                    let start = i;
                    if i + 1 < bytes.len() && bytes[i + 1] == b && (b == b'*' || b == b'/') {
                        i += 1;
                    }
                    tokens.push(Token::Op(s[start..=i].into()));
                }
                _ => return Err(syntax()),
            }
            i += 1;
        }
        if nesting != 0 {
            return Err(syntax());
        }
        tokens.push(Token::End);
        Ok(Self { tokens, pos: 0 })
    }
    fn next(&mut self) -> Token {
        let t = self.tokens[self.pos].clone();
        self.pos += 1;
        t
    }
    fn expression(&mut self, min: u8) -> Result<Expr, Fault> {
        let mut left = match self.next() {
            Token::Number(n) => Expr::Literal(n),
            Token::Quoted => Expr::Literal("'string'".into()),
            Token::Name(n) => {
                if n == "True" || n == "False" || n == "None" {
                    Expr::Literal(n)
                } else {
                    Expr::Unsupported(2)
                }
            }
            Token::Op(op) if op == "+" || op == "-" => {
                Expr::Unary(op.chars().next().unwrap(), Box::new(self.expression(25)?))
            }
            Token::Open => {
                let e = self.expression(0)?;
                if self.next() != Token::Close {
                    return Err(syntax());
                }
                e
            }
            _ => return Err(syntax()),
        };
        if self.tokens[self.pos] == Token::Open {
            self.next();
            let mut count = 1 + left.count();
            if self.tokens[self.pos] != Token::Close {
                count += self.expression(0)?.count();
            }
            if self.next() != Token::Close {
                return Err(syntax());
            }
            left = Expr::Unsupported(count);
        }
        while let Token::Op(op) = &self.tokens[self.pos] {
            let precedence = match op.as_str() {
                "+" | "-" => 10,
                "*" | "/" | "%" | "//" => 20,
                "**" => 30,
                _ => 5,
            };
            if precedence < min {
                break;
            }
            let op = op.clone();
            self.next();
            let right = self.expression(if op == "**" {
                precedence
            } else {
                precedence + 1
            })?;
            left = Expr::Binary(op, Box::new(left), Box::new(right));
        }
        Ok(left)
    }
}
pub fn parse_number(raw: &Value, field: &str, empty_k: bool) -> Result<Decimal, Fault> {
    parse_inner(raw, empty_k).map_err(|e| Fault::new(&e.reason, field))
}
fn parse_inner(raw: &Value, empty_k: bool) -> Result<Decimal, Fault> {
    let raw = raw
        .as_str()
        .ok_or_else(|| Fault::new("TEXT_TYPE_OR_CAPACITY", ""))?;
    if raw.chars().count() > 256 {
        return Err(Fault::new("TEXT_TYPE_OR_CAPACITY", ""));
    }
    let raw = trim(raw);
    if raw.is_empty() {
        return if empty_k {
            Ok(Decimal::integer(1))
        } else {
            Err(Fault::new("EMPTY", ""))
        };
    }
    let expression = normalize(raw);
    if expression.is_empty() || expression.chars().count() > 80 {
        return Err(Fault::new("EXPRESSION_CAPACITY", ""));
    }
    let mut p = Parser::new(&expression)?;
    let tree = p.expression(0)?;
    if p.tokens[p.pos] != Token::End {
        return Err(syntax());
    }
    if tree.count() + 1 > 64 {
        return Err(Fault::new("AST_CAPACITY", ""));
    }
    let n = tree.eval(0)?;
    if !n.field_ok() {
        return Err(Fault::new("FIELD_RANGE", ""));
    }
    if n.scale > 12 {
        return Err(Fault::new("FIELD_SCALE", ""));
    }
    Ok(n)
}
pub fn parse_percent(raw: &Value) -> Result<Decimal, Fault> {
    let fail = |reason| Fault::new(reason, "percent");
    let raw = raw
        .as_str()
        .filter(|s| s.chars().count() <= 256)
        .ok_or_else(|| fail("DISCOUNT_TEXT"))?;
    let s = trim(raw).replace('％', "%");
    let s = trim(s.strip_suffix('%').unwrap_or(&s));
    let converted: String = s
        .chars()
        .map(|c| decimal_digit(c).map_or(c, |d| char::from(b'0' + d)))
        .collect();
    let s = converted.as_str();
    let valid = if let Some((a, b)) = s.split_once('.') {
        !a.is_empty()
            && !b.is_empty()
            && a.bytes().all(|c| c.is_ascii_digit())
            && b.bytes().all(|c| c.is_ascii_digit())
    } else {
        !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit())
    };
    if !valid {
        return Err(fail("DISCOUNT_SYNTAX"));
    }
    let n = Decimal::literal(s).map_err(|_| fail("DISCOUNT_CAPACITY"))?;
    if n.coefficient > BigInt::from(100) * ten(n.scale) || n.scale > 12 {
        return Err(fail("DISCOUNT_CAPACITY"));
    }
    Ok(n)
}

// Unicode 15.0.0 decimal-digit blocks, matching the Python 3.12 baseline.
pub fn decimal_digit(c: char) -> Option<u8> {
    const ZEROES: &[u32] = &[
        0x30, 0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66,
        0xde6, 0xe50, 0xed0, 0xf20, 0x1040, 0x1090, 0x17e0, 0x1810, 0x1946, 0x19d0, 0x1a80, 0x1a90,
        0x1b50, 0x1bb0, 0x1c40, 0x1c50, 0xa620, 0xa8d0, 0xa900, 0xa9d0, 0xa9f0, 0xaa50, 0xabf0,
        0xff10, 0x104a0, 0x10d30, 0x11066, 0x110f0, 0x11136, 0x111d0, 0x112f0, 0x11450, 0x114d0,
        0x11650, 0x116c0, 0x11730, 0x118e0, 0x11950, 0x11c50, 0x11d50, 0x11da0, 0x11f50, 0x16a60,
        0x16ac0, 0x16b50, 0x1d7ce, 0x1d7d8, 0x1d7e2, 0x1d7ec, 0x1d7f6, 0x1e140, 0x1e2f0, 0x1e4f0,
        0x1e950, 0x1fbf0,
    ];
    ZEROES.iter().find_map(|zero| {
        (c as u32)
            .checked_sub(*zero)
            .filter(|n| *n < 10)
            .map(|n| n as u8)
    })
}
