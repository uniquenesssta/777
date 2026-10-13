use crate::{Error, Result, OUTPUT_LIMIT};
use rust_xlsxwriter::{DocProperties, ExcelDateTime, Format, Workbook};
use serde_json::Value;
use sha2::{Digest, Sha256};
fn invalid() -> Error {
    Error::new("OUTPUT_BLOB_INVALID")
}
fn text(v: &Value) -> Result<String> {
    match v {
        Value::String(s) => Ok(s.clone()),
        Value::Number(n) => Ok(n.to_string()),
        _ => Err(invalid()),
    }
}
fn displayed(s: &str) -> String {
    s.chars()
        .map(|ch| {
            if (ch as u32) < 32 && !matches!(ch, '\t' | '\n' | '\r') {
                format!("\\u{:04x}", ch as u32)
            } else {
                ch.to_string()
            }
        })
        .collect()
}
fn dict_text(v: &Value) -> Result<String> {
    let raw = serde_json::to_string(v).map_err(|_| invalid())?;
    let mut out = String::new();
    let mut inside = false;
    let mut escape = false;
    for c in raw.chars() {
        out.push(c);
        if escape {
            escape = false;
        } else if inside && c == '\\' {
            escape = true;
        } else if c == '"' {
            inside = !inside;
        } else if !inside && matches!(c, ',' | ':') {
            out.push(' ');
        }
    }
    Ok(out)
}
fn money(s: &str) -> Result<String> {
    let n = s.parse::<i64>().map_err(|_| invalid())?;
    let mag = n.unsigned_abs();
    Ok(format!(
        "{}{}.{:02}",
        if n < 0 { "-" } else { "" },
        mag / 100,
        mag % 100
    ))
}
fn sheet(book: &mut Workbook, name: &str, rows: Vec<Vec<String>>) -> Result<()> {
    let ws = book.add_worksheet();
    ws.set_name(name).map_err(|_| invalid())?;
    ws.set_freeze_panes(1, 0).map_err(|_| invalid())?;
    let text_format = Format::new().set_num_format("@");
    let header = Format::new().set_num_format("@").set_bold();
    let width = rows.iter().map(Vec::len).max().unwrap_or(1);
    for col in 0..width {
        ws.set_column_width(col as u16, 24).map_err(|_| invalid())?;
    }
    for (row, cells) in rows.iter().enumerate() {
        for (col, value) in cells.iter().enumerate() {
            ws.write_string_with_format(
                row as u32,
                col as u16,
                displayed(value),
                if row == 0 { &header } else { &text_format },
            )
            .map_err(|_| Error::new("OUTPUT_CELL_TEXT_LIMIT"))?;
        }
    }
    Ok(())
}
pub fn write(payload: &Value) -> Result<Vec<u8>> {
    let kind = payload["kind"].as_str().ok_or_else(invalid)?;
    if payload["format"] != "777-output-v1" || !matches!(kind, "excel_quote" | "excel_admin") {
        return Err(Error::new("OUTPUT_VERSION_CONFLICT"));
    }
    let order = &payload["order"];
    let canonical = serde_json::to_vec(payload).map_err(|_| invalid())?;
    if canonical.len() > 2 * 1024 * 1024 {
        return Err(Error::new("OUTPUT_SNAPSHOT_TOO_LARGE"));
    }
    let hash = format!("{:x}", Sha256::digest(canonical));
    let mut workbook = Workbook::new();
    let date = ExcelDateTime::from_ymd(2000, 1, 1).map_err(|_| invalid())?;
    workbook.set_properties(&DocProperties::new().set_creation_datetime(&date));
    sheet(
        &mut workbook,
        "Protocol",
        vec![
            vec!["format".into(), "777-output-v1".into()],
            vec!["job_id".into(), text(&payload["job_id"])?],
            vec!["payload_sha256".into(), hash],
            vec!["kind".into(), kind.into()],
        ],
    )?;
    let mut rows = vec![vec!["field".into(), "value".into()]];
    for key in [
        "order_id",
        "revision",
        "state",
        "price_version_id",
        "rule_version",
        "numeric_profile",
        "created_at",
    ] {
        rows.push(vec![key.into(), text(&order[key])?]);
    }
    let details = order["details"].as_object().ok_or_else(invalid)?;
    if details.len() != 3
        || !["customer", "order_ref", "wechat"]
            .iter()
            .all(|key| details.contains_key(*key))
    {
        return Err(invalid());
    }
    for key in ["customer", "order_ref", "wechat"] {
        rows.push(vec![key.into(), text(&order["details"][key])?]);
    }
    let income = text(&order["income_cents"])?;
    rows.push(vec!["income_cents".into(), income.clone()]);
    rows.push(vec!["income_yuan".into(), money(&income)?]);
    if kind == "excel_admin" {
        for key in ["cost_cents", "profit_cents"] {
            rows.push(vec![key.into(), text(&order[key])?]);
        }
    }
    sheet(&mut workbook, "Order", rows)?;
    let mut headers = vec![
        "sequence",
        "raw",
        "normalized",
        "subtotal_before_cents",
        "income_cents",
    ];
    if kind == "excel_admin" {
        headers.extend(["cost_cents", "profit_cents"]);
    }
    let lines = order["lines"].as_array().ok_or_else(invalid)?;
    if lines.len() > 1000 {
        return Err(Error::new("OUTPUT_LINE_LIMIT"));
    }
    let mut rows = vec![headers.iter().map(|v| v.to_string()).collect()];
    for line in lines {
        let mut row = Vec::new();
        for key in &headers {
            let value = &line[key];
            row.push(if value.is_object() {
                dict_text(value)?
            } else {
                text(value)?
            });
        }
        rows.push(row);
    }
    sheet(&mut workbook, "Lines", rows)?;
    let mut rows = vec![vec![
        "note_id".into(),
        "author".into(),
        "body".into(),
        "created_at".into(),
    ]];
    let notes = order["notes"].as_array().ok_or_else(invalid)?;
    if notes.len() > 50_000 {
        return Err(Error::new("OUTPUT_NOTE_LIMIT"));
    }
    for note in notes {
        rows.push(
            ["note_id", "author", "body", "created_at"]
                .iter()
                .map(|key| text(&note[key]))
                .collect::<Result<_>>()?,
        );
    }
    sheet(&mut workbook, "Notes", rows)?;
    let bytes = workbook.save_to_buffer().map_err(|_| invalid())?;
    if bytes.len() > OUTPUT_LIMIT {
        return Err(Error::new("OUTPUT_TOO_LARGE"));
    }
    Ok(bytes)
}
