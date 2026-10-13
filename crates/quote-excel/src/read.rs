use crate::{Error, Result, CELL_LIMIT, EXPANDED_LIMIT, ROW_LIMIT, SOURCE_LIMIT};
use quick_xml::{events::Event, Reader};
use serde::Serialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{Cursor, Read},
};
use zip::ZipArchive;

#[derive(Debug, Clone, Serialize)]
pub struct Cell {
    pub row: u32,
    pub column: u16,
    pub kind: String,
    pub value: Option<String>,
    pub style: usize,
}
#[derive(Debug, Serialize)]
pub struct Sheet {
    pub name: String,
    pub state: String,
    pub max_row: u32,
    pub max_column: u16,
    pub cells: Vec<Cell>,
    pub hidden_columns: Vec<u16>,
    pub frozen_at: Option<String>,
}
#[derive(Debug, Clone, Default, Serialize)]
pub struct Style {
    pub num_fmt_id: u32,
    pub format_code: String,
    pub bold: bool,
}
#[derive(Debug, Serialize)]
pub struct Book {
    pub format: String,
    pub date_1904: bool,
    pub styles: Vec<Style>,
    pub sheets: Vec<Sheet>,
}
#[derive(Debug)]
enum Xml {
    Start(String, BTreeMap<String, String>),
    End(String),
    Text(String),
}
fn xml_error() -> Error {
    Error::new("XML_CORRUPT_OR_UNSUPPORTED")
}
fn scan(data: &[u8], mut visit: impl FnMut(Xml) -> Result<()>) -> Result<()> {
    let text = std::str::from_utf8(data).map_err(|_| Error::new("XML_ENCODING_UNSUPPORTED"))?;
    if text.contains('\0') {
        return Err(Error::new("XML_ENCODING_UNSUPPORTED"));
    }
    if text.chars().any(|ch| {
        ((ch as u32) < 32 && !matches!(ch, '\t' | '\n' | '\r'))
            || matches!(ch, '\u{fffe}' | '\u{ffff}')
    }) {
        return Err(xml_error());
    }
    let mut r = Reader::from_str(text);
    let mut depth = 0usize;
    let mut roots = 0;
    let mut events = 0usize;
    loop {
        events += 1;
        if events > 8 * CELL_LIMIT {
            return Err(Error::new("XML_STRUCTURE_LIMIT"));
        }
        let event = r.read_event().map_err(|_| xml_error())?;
        let empty = matches!(event, Event::Empty(_));
        match event {
            Event::Start(e) | Event::Empty(e) => {
                if depth == 0 {
                    roots += 1;
                }
                if roots > 1 || depth >= 64 {
                    return Err(xml_error());
                }
                let name = std::str::from_utf8(e.local_name().as_ref())
                    .map_err(|_| xml_error())?
                    .to_owned();
                let mut attrs = BTreeMap::new();
                for a in e.attributes() {
                    let a = a.map_err(|_| xml_error())?;
                    let key = std::str::from_utf8(a.key.as_ref())
                        .map_err(|_| xml_error())?
                        .to_owned();
                    let val = a
                        .decoded_and_normalized_value(
                            quick_xml::XmlVersion::Implicit1_0,
                            r.decoder(),
                        )
                        .map_err(|_| xml_error())?
                        .into_owned();
                    attrs.insert(key, val);
                }
                visit(Xml::Start(name.clone(), attrs))?;
                if empty {
                    visit(Xml::End(name))?;
                } else {
                    depth += 1;
                }
            }
            Event::End(e) => {
                depth = depth.checked_sub(1).ok_or_else(xml_error)?;
                visit(Xml::End(
                    std::str::from_utf8(e.local_name().as_ref())
                        .map_err(|_| xml_error())?
                        .to_owned(),
                ))?;
            }
            Event::Text(e) => {
                let s = e.xml10_content().map_err(|_| xml_error())?.into_owned();
                if depth == 0 && !s.trim().is_empty() {
                    return Err(xml_error());
                }
                visit(Xml::Text(s))?;
            }
            Event::CData(e) => visit(Xml::Text(e.decode().map_err(|_| xml_error())?.into_owned()))?,
            Event::GeneralRef(e) => {
                let text = if let Some(ch) = e.resolve_char_ref().map_err(|_| xml_error())? {
                    ch.to_string()
                } else {
                    match e.decode().map_err(|_| xml_error())?.as_ref() {
                        "amp" => "&",
                        "lt" => "<",
                        "gt" => ">",
                        "quot" => "\"",
                        "apos" => "'",
                        _ => return Err(Error::new("XML_ENTITY_UNSUPPORTED")),
                    }
                    .to_string()
                };
                visit(Xml::Text(text))?;
            }
            Event::DocType(_) => return Err(Error::new("XML_ENTITY_UNSUPPORTED")),
            Event::Decl(e) => {
                if let Some(enc) = e.encoding() {
                    let enc = enc.map_err(|_| xml_error())?;
                    if !enc.eq_ignore_ascii_case(b"utf-8") {
                        return Err(Error::new("XML_ENCODING_UNSUPPORTED"));
                    }
                }
            }
            Event::PI(_) | Event::Comment(_) => {}
            Event::Eof => {
                if roots != 1 || depth != 0 {
                    return Err(xml_error());
                }
                return Ok(());
            }
        }
    }
}
fn root(data: &[u8], expected: &str, namespace: &str) -> Result<()> {
    let text = std::str::from_utf8(data).map_err(|_| xml_error())?;
    let mut reader = Reader::from_str(text);
    loop {
        match reader.read_event().map_err(|_| xml_error())? {
            Event::Start(e) | Event::Empty(e) => {
                if e.local_name().as_ref() != expected.as_bytes() {
                    return Err(Error::new("WORKBOOK_ROOT_REVIEW"));
                }
                let full = e.name();
                let prefix = std::str::from_utf8(full.as_ref())
                    .map_err(|_| xml_error())?
                    .split_once(':')
                    .map(|(p, _)| format!("xmlns:{p}"))
                    .unwrap_or_else(|| "xmlns".into());
                for a in e.attributes() {
                    let a = a.map_err(|_| xml_error())?;
                    if a.key.as_ref() == prefix.as_bytes()
                        && a.decoded_and_normalized_value(
                            quick_xml::XmlVersion::Implicit1_0,
                            reader.decoder(),
                        )
                        .map_err(|_| xml_error())?
                        .as_ref()
                            == namespace
                    {
                        return Ok(());
                    }
                }
                return Err(Error::new("WORKBOOK_NAMESPACE_REVIEW"));
            }
            Event::Eof => return Err(xml_error()),
            _ => {}
        }
    }
}
const SHEET_NS: &str = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
fn number<T: std::str::FromStr>(a: &BTreeMap<String, String>, key: &str) -> Result<T> {
    a.get(key)
        .and_then(|s| s.parse().ok())
        .ok_or_else(xml_error)
}
fn boolean(s: Option<&String>) -> Result<bool> {
    match s.map(String::as_str) {
        None | Some("0" | "false") => Ok(false),
        Some("1" | "true") => Ok(true),
        _ => Err(xml_error()),
    }
}
fn target(base: &str, path: &str) -> Result<String> {
    if path.contains(['\\', ':', '?', '#']) {
        return Err(Error::new("WORKBOOK_RELATIONSHIP_REVIEW"));
    }
    let full = if path.starts_with('/') {
        path.trim_start_matches('/').to_string()
    } else {
        format!("{base}/{path}")
    };
    let mut out = Vec::new();
    for part in full.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if out.pop().is_none() {
                    return Err(xml_error());
                }
            }
            p => out.push(p),
        }
    }
    if out.first() != Some(&"xl") {
        return Err(Error::new("WORKBOOK_RELATIONSHIP_REVIEW"));
    }
    Ok(out.join("/"))
}
fn ooxml_text(s: &str) -> Result<String> {
    let mut units = Vec::new();
    let mut rest = s;
    while !rest.is_empty() {
        if rest.len() >= 7 && rest.starts_with("_x") && rest.as_bytes()[6] == b'_' {
            if let Some(token) = rest.get(2..6) {
                if let Ok(v) = u16::from_str_radix(token, 16) {
                    units.push(v);
                    rest = &rest[7..];
                    continue;
                }
            }
        }
        let ch = rest.chars().next().ok_or_else(xml_error)?;
        units.extend(ch.encode_utf16(&mut [0; 2]).iter().copied());
        rest = &rest[ch.len_utf8()..];
    }
    String::from_utf16(&units).map_err(|_| xml_error())
}
fn shared(data: Option<&Vec<u8>>) -> Result<Vec<String>> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut in_t = false;
    let mut phonetic = false;
    if let Some(data) = data {
        root(data, "sst", SHEET_NS)?;
        scan(data, |event| {
            match event {
                Xml::Start(n, _) if n == "si" => current.clear(),
                Xml::Start(n, _) if n == "rPh" => phonetic = true,
                Xml::End(n) if n == "rPh" => phonetic = false,
                Xml::Start(n, _) if n == "t" => in_t = true,
                Xml::End(n) if n == "t" => in_t = false,
                Xml::Text(s) if in_t && !phonetic => current.push_str(&s),
                Xml::End(n) if n == "si" => {
                    if out.len() >= CELL_LIMIT {
                        return Err(Error::new("SHARED_STRING_LIMIT"));
                    }
                    out.push(ooxml_text(&current)?);
                }
                _ => {}
            }
            Ok(())
        })?;
    }
    Ok(out)
}
fn styles(data: Option<&Vec<u8>>) -> Result<Vec<Style>> {
    let mut out = Vec::new();
    let mut formats = BTreeMap::new();
    let mut fonts = Vec::new();
    let mut in_font = false;
    let mut bold = false;
    let mut cell_xfs = false;
    if let Some(data) = data {
        root(data, "styleSheet", SHEET_NS)?;
        scan(data, |event| {
            match event {
                Xml::Start(n, a) if n == "numFmt" => {
                    let id = number::<u32>(&a, "numFmtId")?;
                    if formats
                        .insert(id, a.get("formatCode").cloned().ok_or_else(xml_error)?)
                        .is_some()
                    {
                        return Err(xml_error());
                    }
                }
                Xml::Start(n, _) if n == "font" => {
                    in_font = true;
                    bold = false;
                }
                Xml::Start(n, a) if n == "b" && in_font => {
                    bold = !matches!(a.get("val").map(String::as_str), Some("0" | "false"))
                }
                Xml::End(n) if n == "font" => {
                    fonts.push(bold);
                    in_font = false;
                }
                Xml::Start(n, _) if n == "cellXfs" => cell_xfs = true,
                Xml::End(n) if n == "cellXfs" => cell_xfs = false,
                Xml::Start(n, a) if n == "xf" && cell_xfs => {
                    let id = a
                        .get("numFmtId")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let font = a
                        .get("fontId")
                        .and_then(|s| s.parse::<usize>().ok())
                        .unwrap_or(0);
                    if out.len() >= 65536 {
                        return Err(Error::new("WORKBOOK_STYLE_LIMIT"));
                    }
                    out.push(Style {
                        num_fmt_id: id,
                        format_code: formats.get(&id).cloned().unwrap_or_default(),
                        bold: fonts.get(font).copied().unwrap_or(false),
                    });
                }
                _ => {}
            }
            Ok(())
        })?;
    }
    if out.is_empty() {
        out.push(Style::default());
    }
    Ok(out)
}
fn coordinate(s: &str) -> Result<(u32, u16)> {
    let mut col = 0u16;
    let mut offset = 0;
    for ch in s.bytes() {
        if !ch.is_ascii_uppercase() {
            break;
        }
        col = col
            .checked_mul(26)
            .and_then(|v| v.checked_add((ch - b'A' + 1) as u16))
            .ok_or_else(xml_error)?;
        offset += 1;
    }
    let row = s
        .get(offset..)
        .and_then(|v| v.parse::<u32>().ok())
        .ok_or_else(xml_error)?;
    if row == 0 || col == 0 {
        return Err(xml_error());
    }
    if row > ROW_LIMIT || col > 64 {
        return Err(Error::new("WORKSHEET_DIMENSION_LIMIT"));
    }
    Ok((row, col))
}
fn worksheet(
    data: &[u8],
    name: &str,
    state: &str,
    strings: &[String],
    styles: &[Style],
) -> Result<Sheet> {
    root(data, "worksheet", SHEET_NS)?;
    let mut sheet = Sheet {
        name: name.into(),
        state: state.into(),
        max_row: 1,
        max_column: 1,
        cells: Vec::new(),
        hidden_columns: Vec::new(),
        frozen_at: None,
    };
    let mut seen = BTreeSet::new();
    let mut cell: Option<Cell> = None;
    let mut text = String::new();
    let mut in_value = false;
    let mut in_text = false;
    let mut phonetic = false;
    let mut kind = String::new();
    let mut inline_present = false;
    let mut row_index = 0;
    let mut ancestors = Vec::<String>::new();
    let mut merges = Vec::new();
    scan(data, |event| {
        match &event {
            Xml::Start(n, _) => {
                if n == "row" && ancestors.last().map(String::as_str) != Some("sheetData")
                    || n == "c" && ancestors.last().map(String::as_str) != Some("row")
                    || n == "v" && ancestors.last().map(String::as_str) != Some("c")
                {
                    return Err(Error::new("WORKSHEET_STRUCTURE_REVIEW"));
                }
                ancestors.push(n.clone());
            }
            Xml::End(_) => {
                ancestors.pop();
            }
            _ => {}
        }
        match event {
            Xml::Start(n, a) if n == "dimension" => {
                if let Some(r) = a.get("ref") {
                    let refs = r.split(':').collect::<Vec<_>>();
                    if refs.len() > 2 {
                        return Err(xml_error());
                    }
                    let start = coordinate(refs[0])?;
                    let (row, col) = coordinate(refs[refs.len() - 1])?;
                    if row < start.0 || col < start.1 {
                        return Err(xml_error());
                    }
                    sheet.max_row = sheet.max_row.max(row);
                    sheet.max_column = sheet.max_column.max(col);
                }
            }
            Xml::Start(n, a) if n == "mergeCell" => {
                let r = a.get("ref").ok_or_else(xml_error)?;
                let parts = r.split(':').collect::<Vec<_>>();
                if parts.len() != 2 {
                    return Err(xml_error());
                }
                let first = coordinate(parts[0])?;
                let last = coordinate(parts[1])?;
                if last.0 < first.0 || last.1 < first.1 {
                    return Err(xml_error());
                }
                if merges.len() >= 128 {
                    return Err(Error::new("MERGED_RANGE_LIMIT"));
                }
                merges.push((first, last));
            }
            Xml::Start(n, a) if n == "row" => {
                row_index = number::<u32>(&a, "r")?;
                if row_index == 0 || row_index > ROW_LIMIT {
                    return Err(Error::new("WORKSHEET_ROW_LIMIT"));
                }
                sheet.max_row = sheet.max_row.max(row_index);
            }
            Xml::Start(n, a) if n == "col" && boolean(a.get("hidden"))? => {
                let min = number::<u16>(&a, "min")?;
                let max = number::<u16>(&a, "max")?;
                if min == 0 || max < min {
                    return Err(xml_error());
                }
                sheet.hidden_columns.extend(min..=max.min(64));
            }
            Xml::Start(n, a) if n == "pane" => {
                if matches!(
                    a.get("state").map(String::as_str),
                    Some("frozen" | "frozenSplit")
                ) {
                    sheet.frozen_at = a.get("topLeftCell").cloned();
                }
            }
            Xml::Start(n, _) if n == "f" => {
                return Err(Error::new("FORMULA_PRESENT_NO_EVALUATION_OR_CACHE_TRUST"))
            }
            Xml::Start(n, _)
                if matches!(
                    n.as_str(),
                    "extLst" | "oleObjects" | "drawing" | "legacyDrawing" | "hyperlink"
                ) =>
            {
                return Err(Error::new("WORKBOOK_EXTENSION_REVIEW"))
            }
            Xml::Start(n, a) if n == "c" => {
                if cell.is_some() {
                    return Err(xml_error());
                }
                let reference = a.get("r").ok_or_else(xml_error)?;
                let (row, column) = coordinate(reference)?;
                if row != row_index || !seen.insert((row, column)) {
                    return Err(Error::new("DUPLICATE_OR_MISPLACED_CELL").at(name, reference));
                }
                let style = a
                    .get("s")
                    .map(|v| v.parse::<usize>())
                    .transpose()
                    .map_err(|_| xml_error())?
                    .unwrap_or(0);
                if style >= styles.len() {
                    return Err(Error::new("WORKBOOK_STYLE_REVIEW"));
                }
                kind = a.get("t").cloned().unwrap_or_else(|| "n".into());
                text.clear();
                inline_present = false;
                cell = Some(Cell {
                    row,
                    column,
                    kind: kind.clone(),
                    value: None,
                    style,
                });
                sheet.max_row = sheet.max_row.max(row);
                sheet.max_column = sheet.max_column.max(column);
            }
            Xml::Start(n, _) if n == "is" => inline_present = true,
            Xml::Start(n, _) if n == "v" => in_value = true,
            Xml::End(n) if n == "v" => in_value = false,
            Xml::Start(n, _) if n == "rPh" => phonetic = true,
            Xml::End(n) if n == "rPh" => phonetic = false,
            Xml::Start(n, _) if n == "t" => in_text = true,
            Xml::End(n) if n == "t" => in_text = false,
            Xml::Text(s) if cell.is_some() && (in_value || in_text && !phonetic) => {
                text.push_str(&s)
            }
            Xml::End(n) if n == "c" => {
                let mut c = cell.take().ok_or_else(xml_error)?;
                c.value = match kind.as_str() {
                    "s" if text.is_empty() => None,
                    "s" => Some(
                        strings
                            .get(text.parse::<usize>().map_err(|_| xml_error())?)
                            .cloned()
                            .ok_or_else(xml_error)?,
                    ),
                    "inlineStr" | "str" => {
                        c.kind = "s".into();
                        if kind == "inlineStr" && inline_present
                            || kind == "str" && !text.is_empty()
                        {
                            Some(ooxml_text(&text)?)
                        } else {
                            None
                        }
                    }
                    "n" if text.is_empty() => None,
                    "n" => {
                        if text.len() > 256
                            || !text
                                .bytes()
                                .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b))
                            || !text.bytes().any(|b| b.is_ascii_digit())
                        {
                            return Err(Error::new("INVALID_NUMERIC_TOKEN"));
                        }
                        Some(text.clone())
                    }
                    "b" if text == "0" || text == "1" => Some(text.clone()),
                    "d" => Some(text.clone()),
                    "e" => return Err(Error::new("CELL_ERROR_REVIEW")),
                    _ => return Err(Error::new("CELL_TYPE_UNSUPPORTED")),
                };
                sheet.cells.push(c);
                if sheet.cells.len() > CELL_LIMIT {
                    return Err(Error::new("WORKSHEET_CELL_LIMIT"));
                }
            }
            _ => {}
        }
        Ok(())
    })
    .map_err(|e| {
        if e.sheet.is_empty() {
            e.at(name, "")
        } else {
            e
        }
    })?;
    if sheet.max_row as usize * sheet.max_column as usize > CELL_LIMIT {
        return Err(Error::new("WORKSHEET_DIMENSION_LIMIT").at(name, ""));
    }
    for (first, last) in merges {
        if sheet.cells.iter().any(|c| {
            (c.row, c.column) != first
                && c.row >= first.0
                && c.row <= last.0
                && c.column >= first.1
                && c.column <= last.1
                && c.value.as_ref().is_some_and(|v| !v.is_empty())
        }) {
            return Err(Error::new("MERGED_CELL_VALUE_REVIEW").at(name, ""));
        }
    }
    sheet.hidden_columns.sort_unstable();
    sheet.hidden_columns.dedup();
    Ok(sheet)
}
pub fn read(raw: &[u8]) -> Result<Book> {
    if raw.len() > SOURCE_LIMIT {
        return Err(Error::new("SOURCE_TYPE_OR_SIZE_LIMIT"));
    }
    let mut zip =
        ZipArchive::new(Cursor::new(raw)).map_err(|_| Error::new("ZIP_STRUCTURE_LIMIT"))?;
    if zip.len() > 2048 {
        return Err(Error::new("ZIP_STRUCTURE_LIMIT"));
    }
    let mut members = BTreeMap::new();
    let mut expanded = 0u64;
    for i in 0..zip.len() {
        let mut entry = zip
            .by_index(i)
            .map_err(|_| Error::new("ZIP_STRUCTURE_LIMIT"))?;
        let name = entry.name().to_string();
        if members.contains_key(&name)
            || name.starts_with('/')
            || name.contains('\\')
            || name.split('/').any(|p| p == ".." || p == ".")
        {
            return Err(Error::new("ZIP_STRUCTURE_LIMIT"));
        }
        expanded = expanded
            .checked_add(entry.size())
            .ok_or_else(|| Error::new("ZIP_EXPANSION_LIMIT"))?;
        if expanded > EXPANDED_LIMIT {
            return Err(Error::new("ZIP_EXPANSION_LIMIT"));
        }
        if entry.encrypted() {
            return Err(Error::new("ENCRYPTED_ZIP_UNSUPPORTED"));
        }
        let lower = name.to_ascii_lowercase();
        if [
            "externallinks",
            "vbaproject",
            "customxml",
            "embeddings",
            "drawings",
            "vml",
            "activex",
        ]
        .iter()
        .any(|s| lower.contains(s))
        {
            return Err(Error::new("WORKBOOK_EXTENSION_REVIEW"));
        }
        let size = entry.size();
        let mut bytes = Vec::new();
        entry
            .by_ref()
            .take(size + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| Error::new("ZIP_CORRUPT"))?;
        if bytes.len() as u64 != size {
            return Err(Error::new("ZIP_CORRUPT"));
        }
        if lower.ends_with(".xml") || lower.ends_with(".rels") {
            scan(&bytes, |event| {
                match event {
                    Xml::Start(n, _) if n == "f" && lower.starts_with("xl/worksheets/") => {
                        return Err(Error::new("FORMULA_PRESENT_NO_EVALUATION_OR_CACHE_TRUST"))
                    }
                    Xml::Start(n, a)
                        if n == "Relationship"
                            && a.get("TargetMode").is_some_and(|m| m == "External") =>
                    {
                        return Err(Error::new("WORKBOOK_RELATIONSHIP_REVIEW"))
                    }
                    _ => {}
                }
                Ok(())
            })?;
        }
        members.insert(name, bytes);
    }
    let get = |name: &str| {
        members
            .get(name)
            .ok_or_else(|| Error::new("WORKBOOK_PART_MISSING"))
    };
    root(
        get("[Content_Types].xml")?,
        "Types",
        "http://schemas.openxmlformats.org/package/2006/content-types",
    )?;
    let mut content_type = false;
    scan(get("[Content_Types].xml")?, |event| {
        if let Xml::Start(n, a) = event {
            if n == "Override" && a.get("PartName").map(String::as_str) == Some("/xl/workbook.xml")
            {
                if content_type || a.get("ContentType").map(String::as_str)!=Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml") {return Err(Error::new("WORKBOOK_CONTENT_TYPE_REVIEW"));}
                content_type = true;
            }
        }
        Ok(())
    })?;
    if !content_type {
        return Err(Error::new("WORKBOOK_CONTENT_TYPE_REVIEW"));
    }
    root(
        get("_rels/.rels")?,
        "Relationships",
        "http://schemas.openxmlformats.org/package/2006/relationships",
    )?;
    let mut main = false;
    scan(get("_rels/.rels")?, |event| {
        if let Xml::Start(n, a) = event {
            if n == "Relationship"
                && a.get("Type")
                    .is_some_and(|t| t.ends_with("/officeDocument"))
            {
                if main || target("", a.get("Target").ok_or_else(xml_error)?)? != "xl/workbook.xml"
                {
                    return Err(Error::new("WORKBOOK_RELATIONSHIP_REVIEW"));
                }
                main = true;
            }
        }
        Ok(())
    })?;
    if !main {
        return Err(Error::new("WORKBOOK_RELATIONSHIP_REVIEW"));
    }
    let mut date_1904 = false;
    let mut sheets = Vec::new();
    let mut names = BTreeSet::new();
    root(get("xl/workbook.xml")?, "workbook", SHEET_NS)?;
    scan(get("xl/workbook.xml")?, |event| {
        if let Xml::Start(n, a) = event {
            match n.as_str() {
                "workbookPr" => date_1904 = boolean(a.get("date1904"))?,
                "sheet" => {
                    let name = a.get("name").cloned().ok_or_else(xml_error)?;
                    let id = a
                        .iter()
                        .find(|(k, _)| k.ends_with(":id"))
                        .map(|(_, v)| v.clone())
                        .ok_or_else(xml_error)?;
                    let state = a.get("state").cloned().unwrap_or_else(|| "visible".into());
                    if name.is_empty()
                        || !names.insert(name.clone())
                        || sheets.len() >= 128
                        || !matches!(state.as_str(), "visible" | "hidden" | "veryHidden")
                    {
                        return Err(Error::new("WORKBOOK_SHEET_REVIEW"));
                    }
                    sheets.push((name, id, state));
                }
                _ => {}
            }
        }
        Ok(())
    })?;
    if sheets.is_empty() {
        return Err(Error::new("WORKBOOK_SHEET_REVIEW"));
    }
    let mut relations = BTreeMap::new();
    let mut string_part = None;
    let mut style_part = None;
    root(
        get("xl/_rels/workbook.xml.rels")?,
        "Relationships",
        "http://schemas.openxmlformats.org/package/2006/relationships",
    )?;
    scan(get("xl/_rels/workbook.xml.rels")?, |event| {
        if let Xml::Start(n, a) = event {
            if n == "Relationship" {
                let id = a.get("Id").ok_or_else(xml_error)?;
                let path = target("xl", a.get("Target").ok_or_else(xml_error)?)?;
                if relations.insert(id.clone(), path.clone()).is_some() {
                    return Err(xml_error());
                }
                match a.get("Type").and_then(|s| s.rsplit('/').next()) {
                    Some("sharedStrings") => string_part = Some(path),
                    Some("styles") => style_part = Some(path),
                    _ => {}
                }
            }
        }
        Ok(())
    })?;
    let strings = shared(string_part.as_ref().map(|s| get(s)).transpose()?)?;
    let styles = styles(style_part.as_ref().map(|s| get(s)).transpose()?)?;
    let mut books = Vec::new();
    let mut count = 0;
    for (name, id, state) in sheets {
        let path = relations.get(&id).ok_or_else(xml_error)?;
        let sheet = worksheet(get(path)?, &name, &state, &strings, &styles)?;
        count += sheet.cells.len();
        if count > CELL_LIMIT {
            return Err(Error::new("WORKSHEET_CELL_LIMIT"));
        }
        books.push(sheet);
    }
    Ok(Book {
        format: "777-excel-read-v1".into(),
        date_1904,
        styles,
        sheets: books,
    })
}
