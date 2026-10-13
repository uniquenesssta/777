use calamine::{Data, Reader as CalamineReader, Xlsx};
use quote_excel::{read, write, SOURCE_LIMIT};
use rust_xlsxwriter::Workbook;
use serde_json::json;
use std::io::{Cursor, Read, Write};
use zip::{write::SimpleFileOptions, ZipArchive, ZipWriter};
fn workbook() -> Vec<u8> {
    let mut w = Workbook::new();
    w.add_worksheet().write_number(0, 0, 1.0).unwrap();
    w.save_to_buffer().unwrap()
}
fn rewrite(raw: &[u8], part: &str, change: impl Fn(&str) -> String) -> Vec<u8> {
    let mut input = ZipArchive::new(Cursor::new(raw)).unwrap();
    let mut output = ZipWriter::new(Cursor::new(Vec::new()));
    for i in 0..input.len() {
        let mut entry = input.by_index(i).unwrap();
        let name = entry.name().to_string();
        let mut bytes = Vec::new();
        entry.read_to_end(&mut bytes).unwrap();
        if name == part {
            bytes = change(std::str::from_utf8(&bytes).unwrap()).into_bytes();
        }
        output
            .start_file(name, SimpleFileOptions::default())
            .unwrap();
        output.write_all(&bytes).unwrap();
    }
    output.finish().unwrap().into_inner()
}
fn payload(kind: &str) -> serde_json::Value {
    json!({"format":"777-output-v1","job_id":"id","kind":kind,"order":{
    "order_id":"order","revision":1,"state":"active","price_version_id":"old","rule_version":"business-v1","numeric_profile":"numeric-v1","created_at":"2026-10-13T00:00:00+00:00",
    "details":{"customer":"=中文<&> \"_x0000_\"","order_ref":"000012","wechat":"微信"},"income_cents":"9223372036854775807","cost_cents":"0","profit_cents":"9223372036854775807","lines":[],"notes":[]}})
}
#[test]
fn calamine_candidate_loses_decimal_token_while_selected_reader_retains_it() {
    let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |s| {
        s.replace("<v>1</v>", "<v>9007199254740993.25</v>")
    });
    let selected = read::read(&raw).unwrap();
    assert_eq!(
        selected.sheets[0].cells[0].value.as_deref(),
        Some("9007199254740993.25")
    );
    let mut candidate = Xlsx::new(Cursor::new(raw)).unwrap();
    let rows = candidate.worksheet_range("Sheet1").unwrap();
    match rows.get((0, 0)).unwrap() {
        Data::Float(value) => assert_ne!(value.to_string(), "9007199254740993.25"),
        other => panic!("unexpected candidate type {other:?}"),
    }
}
#[test]
fn text_roles_precision_and_new_workbook_styles_are_stable() {
    for kind in ["excel_quote", "excel_admin"] {
        let raw = write::write(&payload(kind)).unwrap();
        assert_eq!(raw, write::write(&payload(kind)).unwrap());
        let book = read::read(&raw).unwrap();
        assert_eq!(
            book.sheets
                .iter()
                .map(|s| s.name.as_str())
                .collect::<Vec<_>>(),
            ["Protocol", "Order", "Lines", "Notes"]
        );
        for s in &book.sheets {
            assert_eq!(s.frozen_at.as_deref(), Some("A2"));
            for c in &s.cells {
                if c.value.is_some() {
                    assert_eq!(c.kind, "s");
                }
                assert!(
                    book.styles[c.style].num_fmt_id == 49
                        || book.styles[c.style].format_code == "@"
                );
                if c.row == 1 {
                    assert!(book.styles[c.style].bold);
                }
            }
        }
        let values = book.sheets[1]
            .cells
            .iter()
            .filter_map(|c| c.value.as_deref())
            .collect::<Vec<_>>();
        assert!(values.contains(&"000012"));
        assert!(values.contains(&"92233720368547758.07"));
        assert!(values.contains(&"=中文<&> \"_x0000_\""));
        assert_eq!(values.contains(&"cost_cents"), kind == "excel_admin");
    }
}
#[test]
fn formulas_are_refused_even_with_a_cached_value() {
    for value in ["<f>1+1</f><v>2</v>", "<f>1+1</f>"] {
        let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |s| {
            s.replace("<v>1</v>", value)
        });
        assert_eq!(
            read::read(&raw).unwrap_err().code,
            "FORMULA_PRESENT_NO_EVALUATION_OR_CACHE_TRUST"
        );
    }
}
#[test]
fn corrupt_encoding_entities_and_unknown_namespace_are_refused() {
    for (old, new, code) in [
        (
            "<worksheet",
            "<!DOCTYPE worksheet [<!ENTITY bad 'x'>]><worksheet",
            "XML_ENTITY_UNSUPPORTED",
        ),
        (
            "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "urn:other",
            "WORKBOOK_NAMESPACE_REVIEW",
        ),
    ] {
        let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |s| {
            s.replace(old, new)
        });
        assert_eq!(read::read(&raw).unwrap_err().code, code);
    }
    assert!(read::read(b"broken zip").is_err());
    let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |_| {
        "<worksheet>\0</worksheet>".into()
    });
    assert_eq!(
        read::read(&raw).unwrap_err().code,
        "XML_ENCODING_UNSUPPORTED"
    );
}
#[test]
fn duplicate_cells_and_capacity_fail_instead_of_truncation() {
    let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |s| {
        s.replace("</row>", "<c r=\"A1\"><v>1</v></c></row>")
    });
    assert_eq!(
        read::read(&raw).unwrap_err().code,
        "DUPLICATE_OR_MISPLACED_CELL"
    );
    let raw = rewrite(&workbook(), "xl/worksheets/sheet1.xml", |s| {
        s.replace("A1", "BM1")
    });
    assert_eq!(
        read::read(&raw).unwrap_err().code,
        "WORKSHEET_DIMENSION_LIMIT"
    );
    assert_eq!(
        read::read(&vec![0; SOURCE_LIMIT + 1]).unwrap_err().code,
        "SOURCE_TYPE_OR_SIZE_LIMIT"
    );
}
#[test]
fn external_relationships_fail_closed() {
    let raw = rewrite(&workbook(), "xl/_rels/workbook.xml.rels", |s| {
        s.replace("Target=", "TargetMode=\"External\" Target=")
    });
    assert_eq!(
        read::read(&raw).unwrap_err().code,
        "WORKBOOK_RELATIONSHIP_REVIEW"
    );
}
#[test]
fn output_version_and_financial_capacity_are_rejected() {
    let mut p = payload("excel_quote");
    p["format"] = json!("future");
    assert_eq!(
        write::write(&p).unwrap_err().code,
        "OUTPUT_VERSION_CONFLICT"
    );
    p["format"] = json!("777-output-v1");
    p["order"]["income_cents"] = json!("9223372036854775808");
    assert!(write::write(&p).is_err());
}
