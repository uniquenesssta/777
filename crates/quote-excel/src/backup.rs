//! Readable, macro-free daily backup. Values are text so IDs and exact decimals survive.
use crate::{Error, Result};
use rust_xlsxwriter::{DocProperties, ExcelDateTime, Format, Workbook};
use serde_json::Value;
fn bad() -> Error {
    Error::new("BACKUP_EXCEL_INVALID")
}
fn write_sheet(book: &mut Workbook, name: &str, rows: &[Vec<String>]) -> Result<()> {
    // Split sheets before Excel's row limit; never silently omit rows.
    let Some(header) = rows.first() else {
        return Ok(());
    };
    let chunks = rows[1..].chunks(999_999);
    let count = chunks.len().max(1);
    for part in 0..count {
        let start = (part * 999_999 + 1).min(rows.len());
        let end = (start + 999_999).min(rows.len());
        let chunk = std::iter::once(header).chain(rows[start..end].iter());
        let ws = book.add_worksheet();
        ws.set_name(if part == 0 {
            name.to_owned()
        } else {
            format!("{name}_{}", part + 1)
        })
        .map_err(|_| bad())?;
        ws.set_freeze_panes(1, 0).map_err(|_| bad())?;
        let style = Format::new().set_num_format("@");
        let head = style.clone().set_bold();
        for j in 0..header.len() {
            ws.set_column_width(j as u16, 24).map_err(|_| bad())?;
        }
        for (i, row) in chunk.enumerate() {
            for (j, s) in row.iter().enumerate() {
                ws.write_string_with_format(
                    i as u32,
                    j as u16,
                    s,
                    if i == 0 { &head } else { &style },
                )
                .map_err(|_| bad())?;
            }
        }
    }
    Ok(())
}
fn chinese(key: &str) -> &str {
    match key {
        "product_id" => "商品标识",
        "price_version_id" => "价格版本标识",
        "customer" => "客户名称",
        "order_ref" => "业务单号",
        "wechat" => "联系方式",
        "q" => "数量",
        "h" => "高（米）",
        "w" => "宽（米）",
        "sale" => "销售单价（元，计价方式见pricing_mode）",
        "cost" => "成本单价（元）",
        "k" => "倍率",
        "percent" => "折扣百分数（90表示九折）",
        "single" => "单件计价标志（true为单件）",
        "pricing_mode" => "计价方式（manual手填；cost_plus成本乘倍率；无此字段为历史单价乘倍率）",
        "line_kind" => "明细类型（normal商品；discount折扣）",
        "name" => "显示名称",
        "source_base64" => "已导入源文件原始字节（base64）",
        "source_bytes" => "已导入源文件字节数",
        "id" => "主体编号",
        "singleton" => "唯一记录标志",
        "schema_version" => "结构版本",
        "schema_hash" => "结构校验值",
        "ledger_id" => "账本编号",
        "revision" => "修订号",
        "active_price_id" => "当前价格版本",
        "price_id" => "价格版本编号",
        "payload_json" => "冻结内容",
        "payload_sha256" => "内容校验值",
        "rule_version" => "计价规则版本",
        "numeric_profile" => "数值精度规则",
        "published_by" => "发布人编号",
        "created_at" => "创建时间",
        "request_id" => "操作请求编号",
        "actor_id" => "操作人编号",
        "fingerprint" => "请求指纹",
        "operation" => "操作类型",
        "result_json" => "原始操作回执",
        "ledger_revision" => "账本修订号",
        "order_id" => "订单编号",
        "owner_id" => "订单归属人编号",
        "input_json" => "原始报价输入",
        "details_json" => "客户、单号与联系方式",
        "income_cents" => "收入（分）",
        "cost_cents" => "成本（分）",
        "profit_cents" => "利润（分）",
        "state" => "状态",
        "line_id" => "明细编号",
        "sequence" => "顺序",
        "kind" => "类型",
        "raw_json" => "原始明细与折扣",
        "normalized_json" => "标准化明细",
        "price_json" => "成交时冻结价格",
        "subtotal_before_cents" => "本行前小计（分）",
        "note_id" => "备注编号",
        "author_id" => "备注人编号",
        "body" => "备注内容",
        "batch_id" => "导入批次编号",
        "source_sha256" => "导入源校验值",
        "adapter_version" => "导入适配版本",
        "source_schema" => "导入源格式",
        "status" => "处理状态",
        "mapping_json" => "导入字段映射",
        "report_json" => "导入报告",
        "event_id" => "事件编号",
        "before_json" => "操作前状态",
        "after_json" => "操作后状态",
        "job_id" => "输出任务编号",
        "role" => "业务角色",
        "attempts" => "尝试次数",
        "error" => "失败原因",
        "blob_sha256" => "附件校验值",
        "size" => "附件字节数",
        "output_path" => "原电脑输出路径（仅供参考）",
        "settings_revision" => "输出设置修订号",
        "at" => "事件时间",
        "username" => "主体名称",
        "enabled" => "备份时是否启用（1是0否）",
        _ => "原始业务字段",
    }
}
fn value(v: &Value) -> String {
    match v {
        Value::Null => "〈空值〉".into(),
        Value::String(s) => s.clone(),
        _ => v.to_string(),
    }
}
fn flatten(v: &Value, path: String, out: &mut Vec<Vec<String>>, source: &str, row: usize) {
    match v {
        Value::Object(m) => {
            for (k, v) in m {
                flatten(
                    v,
                    format!("{path}/{}", k.replace('~', "~0").replace('/', "~1")),
                    out,
                    source,
                    row,
                )
            }
        }
        Value::Array(a) => {
            for (i, v) in a.iter().enumerate() {
                flatten(v, format!("{path}/{i}"), out, source, row)
            }
        }
        _ => {
            let label = chinese(path.rsplit('/').next().unwrap_or(&path)).to_string();
            out.push(vec![source.into(), row.to_string(), path, value(v), label]);
        }
    }
}
pub fn write(data: &Value) -> Result<Vec<u8>> {
    let mut book = Workbook::new();
    let stamp = data["created_at"].as_str().unwrap_or("2000-01-01T00:00:00");
    let created =
        ExcelDateTime::parse_from_str(stamp.get(..19).ok_or_else(bad)?).map_err(|_| bad())?;
    book.set_properties(&DocProperties::new().set_creation_datetime(&created));
    crate::readable::write(
        &mut book,
        &crate::readable::backup_orders(data)?,
        true,
        &format!(
            "每日完整备份 · {} · 快照 {}",
            value(&data["business_date"]),
            value(&data["snapshot_id"])
        ),
    )?;
    let mut info = vec![vec!["项目".into(), "说明".into()]];
    for (k, label) in [
        ("format", "恢复格式"),
        ("snapshot_id", "快照编号"),
        ("created_at", "生成时间（UTC）"),
        ("business_date", "业务日期（北京时间）"),
        ("source_version", "源版本"),
    ] {
        info.push(vec![label.into(), value(&data[k])]);
    }
    info.push(vec!["阅读规则".into(),"编号与数值均按文本保存；*_cents单位为分；〈空值〉表示NULL，空字符串为空白。JSON字段另见结构字段；过长值按长文本表分段。软件恢复请使用同快照的.qbackup文件。".into()]);
    info.push(vec![
        "账本编号".into(),
        value(&data["inventory"]["ledger_id"]),
    ]);
    info.push(vec!["表间关联".into(), "订单.price_id→价格.price_id；明细/备注/状态事件.order_id→订单.order_id；owner_id/actor_id/author_id/published_by→人员.id；request_id→操作回执.request_id。客户信息在details_json，商品与数量/折扣在input_json及明细，完整展开见结构字段。".into()]);
    info.push(vec!["状态与拆表".into(), "订单active有效、void作废；状态历史见audit_events。空值〈空值〉、零值0、空字符串空白。每表超过999999条数据另分表并重复标题；行号按原表连续计数。长文本按分段号连接；所有数据均为文本，不执行公式。".into()]);
    let mut dictionary = vec![vec![
        "工作表".into(),
        "字段".into(),
        "中文名称".into(),
        "说明".into(),
    ]];
    let mut long = vec![vec![
        "工作表".into(),
        "数据行（从1起）".into(),
        "字段".into(),
        "分段（从1起）".into(),
        "内容".into(),
    ]];
    let mut nested = vec![vec![
        "工作表".into(),
        "数据行（从1起）".into(),
        "字段路径（JSON Pointer）".into(),
        "原始值".into(),
        "中文字段说明".into(),
    ]];
    let mut tables = Vec::new();
    for (group, prefix) in [("ledger", "账本"), ("outputs", "输出")] {
        for (k, v) in data[group].as_object().ok_or_else(bad)? {
            tables.push((format!("{prefix}_{k}"), v.clone()));
        }
    }
    tables.push(("人员".into(), data["users"].clone()));
    for (name, t) in tables {
        let cols = t["columns"].as_array().ok_or_else(bad)?;
        let records = t["rows"].as_array().ok_or_else(bad)?;
        info.push(vec![format!("{name} 数据行数"), records.len().to_string()]);
        for c in cols {
            let key = c.as_str().ok_or_else(bad)?;
            let meaning = if key.ends_with("_cents") {
                "金额，单位：分，精确整数"
            } else if key.ends_with("_id") || key == "id" {
                "关联编号，按原值匹配对应表"
            } else if key.ends_with("_json") {
                "完整结构值；展开内容见结构字段"
            } else if key.ends_with("_at") {
                "原始时间，保留时区"
            } else {
                "原始业务字段；保持源值"
            };
            dictionary.push(vec![
                name.clone(),
                key.into(),
                chinese(key).into(),
                meaning.into(),
            ]);
        }
        let mut rows = vec![cols.iter().map(value).collect::<Vec<_>>()];
        for (i, r) in records.iter().enumerate() {
            let mut row = Vec::new();
            for (j, v) in r.as_array().ok_or_else(bad)?.iter().enumerate() {
                if cols[j].as_str().is_some_and(|s| s.ends_with("_json")) {
                    if let Some(s) = v.as_str() {
                        if let Ok(parsed) = serde_json::from_str::<Value>(s) {
                            flatten(&parsed, value(&cols[j]), &mut nested, &name, i + 1);
                        }
                    }
                }
                let s = value(v);
                let chars = s.chars().collect::<Vec<_>>();
                if s.encode_utf16().count() > 30000 {
                    for (part, c) in chars.chunks(12000).enumerate() {
                        long.push(vec![
                            name.clone(),
                            (i + 1).to_string(),
                            value(&cols[j]),
                            (part + 1).to_string(),
                            c.iter().collect(),
                        ]);
                    }
                    row.push("见长文本表（按工作表、数据行、字段关联）".into());
                } else {
                    row.push(s);
                }
            }
            rows.push(row);
        }
        write_sheet(&mut book, &name, &rows)?;
    }
    // Nested strings may also be long; retain the full value in the long-text table.
    for (i, r) in nested.iter_mut().enumerate().skip(1) {
        let s = &r[3];
        if s.encode_utf16().count() > 30000 {
            for (part, c) in s.chars().collect::<Vec<_>>().chunks(12000).enumerate() {
                long.push(vec![
                    "结构字段".into(),
                    i.to_string(),
                    "原始值".into(),
                    (part + 1).to_string(),
                    c.iter().collect(),
                ]);
            }
            r[3] = "见长文本表".into();
        }
    }
    write_sheet(&mut book, "说明", &info)?;
    write_sheet(&mut book, "字段字典", &dictionary)?;
    write_sheet(&mut book, "结构字段", &nested)?;
    write_sheet(&mut book, "长文本", &long)?;
    let files = data["blobs"].as_object().ok_or_else(bad)?;
    let mut attachments = vec![vec!["附件".into(), "保存方式".into()]];
    for name in files.keys() {
        attachments.push(vec![name.clone(), "原始文件随同快照.qbackup保存".into()]);
    }
    write_sheet(&mut book, "附件关联", &attachments)?;
    book.save_to_buffer().map_err(|_| bad())
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn literal_strings_and_long_values() {
        let t = json!({"columns":["id","body"],"rows":[["001234567890123456789","=1+1"],["2","字".repeat(40000)]]});
        let data =
            json!({"ledger":{"notes":t},"outputs":{},"users":{"columns":[],"rows":[]},"blobs":{}});
        let bytes = write(&data).unwrap();
        use calamine::{Reader, Xlsx};
        let mut b = Xlsx::new(std::io::Cursor::new(bytes)).unwrap();
        let s = b.worksheet_range("账本_notes").unwrap();
        assert_eq!(
            s.get_value((1, 0)).unwrap().to_string(),
            "001234567890123456789"
        );
        assert_eq!(s.get_value((1, 1)).unwrap().to_string(), "=1+1");
        assert!(b.worksheet_formula("账本_notes").unwrap().is_empty());
        let long = b.worksheet_range("长文本").unwrap();
        let joined = long
            .rows()
            .skip(1)
            .map(|r| r[4].to_string())
            .collect::<String>();
        assert_eq!(joined, "字".repeat(40000));
    }
}
