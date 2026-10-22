//! Human-readable business views shared by backups and newly requested reports.
use crate::{Error, Result};
use rust_xlsxwriter::{Color, Format, Workbook, Worksheet};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use time::{format_description::well_known::Rfc3339, OffsetDateTime, UtcOffset};
fn bad() -> Error {
    Error::new("BUSINESS_EXCEL_INVALID")
}
fn string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        _ => v.to_string(),
    }
}
fn cents(v: &Value) -> Result<i128> {
    string(v).parse().map_err(|_| bad())
}
fn yuan(v: i128) -> String {
    format!(
        "{}{}.{:02}",
        if v < 0 { "-" } else { "" },
        v.unsigned_abs() / 100,
        v.unsigned_abs() % 100
    )
}
fn local(raw: &str) -> String {
    OffsetDateTime::parse(raw, &Rfc3339)
        .ok()
        .map(|t| {
            let t = t.to_offset(UtcOffset::from_hms(8, 0, 0).unwrap());
            format!(
                "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
                t.year(),
                t.month() as u8,
                t.day(),
                t.hour(),
                t.minute(),
                t.second()
            )
        })
        .unwrap_or_else(|| format!("日期待核对 {raw}"))
}
fn records(t: &Value) -> Result<Vec<Value>> {
    let columns = t["columns"].as_array().ok_or_else(bad)?;
    t["rows"]
        .as_array()
        .ok_or_else(bad)?
        .iter()
        .map(|r| {
            let r = r
                .as_array()
                .filter(|r| r.len() == columns.len())
                .ok_or_else(bad)?;
            Ok(Value::Object(
                columns
                    .iter()
                    .zip(r)
                    .map(|(k, v)| Ok((k.as_str().ok_or_else(bad)?.into(), v.clone())))
                    .collect::<Result<Map<String, Value>>>()?,
            ))
        })
        .collect()
}
pub fn backup_orders(data: &Value) -> Result<Vec<Value>> {
    // Tiny synthetic raw-table tests need not include a business ledger.
    if data["ledger"]["orders"].is_null() {
        return Ok(vec![]);
    }
    let mut orders = records(&data["ledger"]["orders"])?;
    let mut lines: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for mut l in records(&data["ledger"]["lines"])? {
        for (source, target) in [("raw_json", "raw"), ("normalized_json", "normalized")] {
            l[target] =
                serde_json::from_str(l[source].as_str().ok_or_else(bad)?).map_err(|_| bad())?;
        }
        lines.entry(string(&l["order_id"])).or_default().push(l);
    }
    let mut notes: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for n in records(&data["ledger"]["notes"])? {
        notes.entry(string(&n["order_id"])).or_default().push(n);
    }
    for o in &mut orders {
        o["details"] =
            serde_json::from_str(o["details_json"].as_str().ok_or_else(bad)?).map_err(|_| bad())?;
        let input: Value =
            serde_json::from_str(o["input_json"].as_str().ok_or_else(bad)?).map_err(|_| bad())?;
        if let Some(price) = input.get("final_price") {
            o["final_price"] = price.clone();
        }
        let key = string(&o["order_id"]);
        let mut ls = lines.remove(&key).unwrap_or_default();
        ls.sort_by_key(|l| l["sequence"].as_i64().unwrap_or(0));
        o["lines"] = json!(ls);
        o["notes"] = json!(notes.remove(&key).unwrap_or_default());
        o["history"] = json!([]);
    }
    if !data["ledger"]["order_versions"].is_null() {
        for h in records(&data["ledger"]["order_versions"])? {
            let snap: Value = serde_json::from_str(h["snapshot_json"].as_str().ok_or_else(bad)?)
                .map_err(|_| bad())?;
            if let Some(o) = orders.iter_mut().find(|o| o["order_id"] == h["order_id"]) {
                let a = &snap["order"];
                o["history"].as_array_mut().ok_or_else(bad)?.push(json!({"revision":h["revision"],"created_at":h["created_at"],"details":serde_json::from_str::<Value>(a["details_json"].as_str().ok_or_else(bad)?).map_err(|_|bad())?,"income_cents":a["income_cents"],"cost_cents":a["cost_cents"],"profit_cents":a["profit_cents"]}));
            }
        }
    }
    if !data["ledger"]["audit_events"].is_null() {
        for a in records(&data["ledger"]["audit_events"])? {
            if a["operation"] == "delete_order" {
                orders.retain(|o| o["order_id"] != a["order_id"]);
                continue;
            }
            if let Some(o) = orders.iter_mut().find(|o| o["order_id"] == a["order_id"]) {
                if string(&a["created_at"]) > string(&o["updated_at"]) {
                    o["updated_at"] = a["created_at"].clone();
                }
            }
        }
    }
    Ok(orders)
}
const HEADERS: [&str; 21] = [
    "日期 / 时间（北京）",
    "客户 / 淘宝 ID",
    "微信号",
    "订单号",
    "记录类型",
    "商品 / 项目",
    "计价方式",
    "高（米）",
    "宽（米）",
    "数量",
    "销售单价（元）",
    "折扣（%）",
    "明细金额（元）",
    "订单收入（元）",
    "订单成本（元）",
    "订单利润（元）",
    "订单状态",
    "备注",
    "订单标识",
    "销售系数 K",
    "最后修改时间（北京）",
];
struct Writer<'a> {
    book: &'a mut Workbook,
    month: String,
    part: u32,
    row: u32,
    normal: Format,
    total: Format,
    header: Format,
}
impl Writer<'_> {
    fn sheet(&mut self) -> Result<&mut Worksheet> {
        let name = if self.part == 1 {
            self.month.clone()
        } else {
            format!("{}（{}）", self.month, self.part)
        };
        if self.row == 0 {
            let ws = self.book.add_worksheet();
            ws.set_name(&name).map_err(|_| bad())?;
            ws.set_freeze_panes(1, 4).map_err(|_| bad())?;
            for (i, w) in [
                22, 24, 23, 26, 14, 24, 12, 12, 12, 12, 18, 12, 18, 18, 18, 18, 12, 44, 38, 14, 22,
            ]
            .iter()
            .enumerate()
            {
                ws.set_column_width(i as u16, *w).map_err(|_| bad())?;
            }
            for (i, h) in HEADERS.iter().enumerate() {
                ws.write_string_with_format(0, i as u16, *h, &self.header)
                    .map_err(|_| bad())?;
            }
            ws.set_row_height(0, 30).map_err(|_| bad())?;
            self.row = 1;
        }
        self.book.worksheet_from_name(&name).map_err(|_| bad())
    }
    fn push(&mut self, cells: Vec<String>, total: bool) -> Result<()> {
        if self.row >= 1_000_000 {
            self.part += 1;
            self.row = 0;
        }
        self.sheet()?;
        let row = self.row;
        let style = if total {
            self.total.clone()
        } else {
            self.normal.clone()
        };
        let ws = self.sheet()?;
        for (i, s) in cells.iter().enumerate() {
            // Continuation rows below preserve all long text instead of cutting it.
            if s.encode_utf16().count() > 30000 {
                return Err(bad());
            }
            ws.write_string_with_format(row, i as u16, s, &style)
                .map_err(|_| bad())?;
        }
        self.row += 1;
        let last = self.row - 1;
        self.sheet()?
            .autofilter(0, 0, last, 20)
            .map_err(|_| bad())?;
        Ok(())
    }
    fn summary(&mut self, label: &str, money: [i128; 3], admin: bool) -> Result<()> {
        let mut row = vec![String::new(); 21];
        row[0] = label.into();
        row[4] = "汇总".into();
        row[13] = yuan(money[0]);
        if admin {
            row[14] = yuan(money[1]);
            row[15] = yuan(money[2]);
        }
        self.push(row, true)
    }
}
pub fn write(book: &mut Workbook, orders: &[Value], admin: bool, description: &str) -> Result<()> {
    let normal = Format::new()
        .set_num_format("@")
        .set_font_name("Microsoft YaHei")
        .set_font_size(10)
        .set_text_wrap();
    let header = normal
        .clone()
        .set_bold()
        .set_background_color(Color::RGB(0xEEEEFF))
        .set_font_color(Color::RGB(0x4945B8));
    let total = normal
        .clone()
        .set_bold()
        .set_background_color(Color::RGB(0xF5F6F8));
    let ws = book.add_worksheet();
    ws.set_name("阅读说明").map_err(|_| bad())?;
    ws.set_column_width(0, 22).map_err(|_| bad())?;
    ws.set_column_width(1, 100).map_err(|_| bad())?;
    for (i,(a,b)) in [("项目","说明"),("内容",description),("排列","按北京时间自然月分表，月内按日、订单、商品顺序排列；未知日期单独列出。"),("金额","金额单位为元；订单收入/成本/利润只写在订单合计行，商品金额另列。日小计/月合计是汇总展示，不可与订单合计重复相加。"),("状态","作废订单保留展示，但不计入日/月有效合计。当前版本仍归原订单日期，修改记录保留实际修改时间。"),("编号与精度","编号、金额以精确文本保留，不丢前导零和长数字，不执行输入的公式。"),("完整数据","本表供阅读与核对；金额为所选快照。每日备份另含完整辅助表，并通过同快照的 .qbackup 恢复。报表不是完整恢复包。"),("记录数",&orders.len().to_string())].iter().enumerate(){ws.write_string_with_format(i as u32,0,*a,if i==0{&header}else{&normal}).map_err(|_|bad())?;ws.write_string_with_format(i as u32,1,*b,if i==0{&header}else{&normal}).map_err(|_|bad())?;ws.set_row_height(i as u32,if i==0{26.0}else{44.0}).map_err(|_|bad())?;}
    if orders
        .iter()
        .any(|o| o["history"].as_array().is_some_and(|v| !v.is_empty()))
    {
        let ws = book.add_worksheet();
        ws.set_name("订单修改记录").map_err(|_| bad())?;
        ws.set_freeze_panes(1, 0).map_err(|_| bad())?;
        for (i, h) in [
            "订单号",
            "客户 / 淘宝 ID",
            "微信号",
            "保存前版本",
            "修改时间（北京）",
            "原收入（元）",
            "原成本（元）",
            "原利润（元）",
            "订单标识",
        ]
        .iter()
        .enumerate()
        {
            ws.set_column_width(i as u16, 26).map_err(|_| bad())?;
            ws.write_string_with_format(0, i as u16, *h, &header)
                .map_err(|_| bad())?;
        }
        let mut row = 1;
        for o in orders {
            for h in o["history"].as_array().into_iter().flatten() {
                let mut cells = vec![
                    string(&h["details"]["order_ref"]),
                    string(&h["details"]["customer"]),
                    string(&h["details"]["wechat"]),
                    string(&h["revision"]),
                    local(h["created_at"].as_str().unwrap_or("")),
                    yuan(cents(&h["income_cents"])?),
                    String::new(),
                    String::new(),
                    string(&o["order_id"]),
                ];
                if admin {
                    cells[6] = yuan(cents(&h["cost_cents"])?);
                    cells[7] = yuan(cents(&h["profit_cents"])?);
                }
                for (i, v) in cells.iter().enumerate() {
                    ws.write_string_with_format(row, i as u16, v, &normal)
                        .map_err(|_| bad())?;
                }
                row += 1;
            }
        }
    }
    let mut months: BTreeMap<String, Vec<(String, &Value)>> = BTreeMap::new();
    for o in orders {
        let stamp = local(o["created_at"].as_str().unwrap_or(""));
        let month = if stamp.starts_with("日期待核对") {
            "日期待核对".into()
        } else {
            format!("{}年{}月", &stamp[..4], &stamp[5..7])
        };
        months.entry(month).or_default().push((stamp, o));
    }
    for (month, mut os) in months {
        os.sort_by(|a, b| (&a.0, string(&a.1["order_id"])).cmp(&(&b.0, string(&b.1["order_id"]))));
        let mut w = Writer {
            book,
            month,
            part: 1,
            row: 0,
            normal: normal.clone(),
            total: total.clone(),
            header: header.clone(),
        };
        let (mut date, mut day, mut sum) = (String::new(), [0i128; 3], [0i128; 3]);
        for (stamp, o) in os {
            let d = if stamp.starts_with("日期待核对") {
                stamp.clone()
            } else {
                stamp[..10].into()
            };
            if d != date && !date.is_empty() {
                w.summary(&format!("{date} 日小计"), day, admin)?;
                day = [0; 3];
            }
            date = d;
            let mut row = vec![String::new(); 21];
            row[0] = stamp;
            row[1] = string(&o["details"]["customer"]);
            row[2] = string(&o["details"]["wechat"]);
            row[3] = string(&o["details"]["order_ref"]);
            row[4] = "订单合计".into();
            row[16] = if o["state"] == "void" {
                "已作废"
            } else {
                "有效"
            }
            .into();
            row[18] = string(&o["order_id"]);
            row[20] = o["updated_at"].as_str().map(local).unwrap_or_default();
            for (i, key) in ["income_cents", "cost_cents", "profit_cents"]
                .iter()
                .enumerate()
            {
                if i == 0 || admin {
                    let n = cents(&o[*key])?;
                    row[13 + i] = yuan(n);
                    if o["state"] != "void" {
                        day[i] = day[i].checked_add(n).ok_or_else(bad)?;
                        sum[i] = sum[i].checked_add(n).ok_or_else(bad)?;
                    }
                }
            }
            if o["final_price"]
                .as_str()
                .is_some_and(|s| !s.trim().is_empty())
            {
                row[17] = "按最终成交价结算".into();
            }
            w.push(row.clone(), true)?;
            for l in o["lines"].as_array().ok_or_else(bad)? {
                let mut r = vec![String::new(); 21];
                r[3] = row[3].clone();
                r[18] = row[18].clone();
                r[16] = row[16].clone();
                if l["raw"]["line_kind"] == "discount" {
                    r[4] = "顺序折扣".into();
                    r[5] = "对上方参与折扣的商品打折".into();
                    r[11] = string(&l["normalized"]["percent"]);
                } else {
                    r[4] = "商品明细".into();
                    r[5] = string(&l["raw"]["product_id"]);
                    if let Some(name) = l["raw"]["name"].as_str().filter(|s| !s.is_empty()) {
                        r[5] = format!("{name}（{}）", r[5]);
                    }
                    r[19] = string(&l["normalized"]["k"]);
                    r[6] = if l["normalized"]["h"].is_null() {
                        "单件"
                    } else {
                        "面积"
                    }
                    .into();
                    for (i, key) in ["h", "w", "q", "sale"].iter().enumerate() {
                        r[7 + i] = string(&l["normalized"][*key]);
                    }
                }
                r[12] = yuan(cents(&l["income_cents"])?);
                w.push(r, false)?;
            }
            if o["final_price"]
                .as_str()
                .is_some_and(|s| !s.trim().is_empty())
            {
                let calculated = o["lines"]
                    .as_array()
                    .ok_or_else(bad)?
                    .iter()
                    .try_fold(0i128, |sum, l| {
                        Ok::<_, Error>(sum + cents(&l["income_cents"])?)
                    })?;
                let mut r = vec![String::new(); 21];
                r[3] = row[3].clone();
                r[18] = row[18].clone();
                r[4] = "成交调价".into();
                r[12] = yuan(cents(&o["income_cents"])? - calculated);
                w.push(r, false)?;
            }
            for n in o["notes"].as_array().ok_or_else(bad)? {
                let body = string(&n["body"]);
                for (i, chars) in body.chars().collect::<Vec<_>>().chunks(12000).enumerate() {
                    let mut r = vec![String::new(); 21];
                    r[0] = local(n["created_at"].as_str().unwrap_or(""));
                    r[3] = row[3].clone();
                    r[4] = if i == 0 { "备注" } else { "备注续行" }.into();
                    r[17] = chars.iter().collect();
                    r[18] = row[18].clone();
                    w.push(r, false)?;
                }
            }
        }
        w.summary(&format!("{date} 日小计"), day, admin)?;
        w.summary("本月有效订单合计", sum, admin)?;
    }
    Ok(())
}
