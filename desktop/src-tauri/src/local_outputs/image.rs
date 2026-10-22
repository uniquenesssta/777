use crate::{DesktopError as Error, Result};
use quote_ledger::store::{encoded, hash};
use serde_json::Value;
const LIMIT: usize = 4 * 1024 * 1024;
fn fail<T>(status: u16, code: &str) -> Result<T> {
    Err(Error::new(status, code))
}
use super::render::font;
fn money(v: &Value) -> Result<String> {
    let n = v
        .as_str()
        .ok_or_else(|| Error::new(422, "OUTPUT_SNAPSHOT_INVALID"))?
        .parse::<i64>()
        .map_err(|_| Error::new(422, "OUTPUT_SNAPSHOT_INVALID"))?;
    let m = n.unsigned_abs();
    Ok(format!(
        "{}{}.{:02}",
        if n < 0 { "-" } else { "" },
        m / 100,
        m % 100
    ))
}
pub fn render(payload: &Value) -> Result<Vec<u8>> {
    let f = font()?;
    let o = &payload["order"];
    let mut lines = vec![
        "Quotation / 报价".into(),
        o["order_id"].as_str().unwrap_or("").into(),
        format!("Revision / 版本: {}", o["revision"]),
        format!("State / 状态: {}", o["state"].as_str().unwrap_or("")),
    ];
    for (label, k) in [
        ("客户", "customer"),
        ("订单号", "order_ref"),
        ("微信", "wechat"),
    ] {
        lines.push(format!(
            "{label}: {}",
            o["details"][k].as_str().unwrap_or("")
        ))
    }
    lines.push(format!("最终成交价: {} 元", money(&o["income_cents"])?));
    for l in o["lines"]
        .as_array()
        .ok_or_else(|| Error::new(422, "OUTPUT_SNAPSHOT_INVALID"))?
    {
        let name = l["raw"]["name"]
            .as_str()
            .filter(|s| !s.is_empty())
            .or(l["raw"]["product_id"].as_str())
            .unwrap_or("折扣");
        lines.push(format!(
            "{}. {name} {} 元",
            l["sequence"],
            money(&l["income_cents"])?
        ));
    }
    for n in o["notes"]
        .as_array()
        .ok_or_else(|| Error::new(422, "OUTPUT_SNAPSHOT_INVALID"))?
    {
        lines.push(format!("备注: {}", n["body"].as_str().unwrap_or("")));
    }
    let wrapped = lines
        .iter()
        .flat_map(|line| {
            let chars = line.chars().collect::<Vec<_>>();
            if chars.is_empty() {
                vec![String::new()]
            } else {
                chars
                    .chunks(36)
                    .map(|a| a.iter().collect())
                    .collect::<Vec<String>>()
            }
        })
        .collect::<Vec<_>>();
    if wrapped.len() > 400 {
        return fail(422, "OUTPUT_IMAGE_TOO_TALL");
    }
    let height = 32 + wrapped.len() * 28;
    let width = 800;
    let mut pixels = vec![255u8; width * height];
    for (row, line) in wrapped.iter().enumerate() {
        let mut x = 20f32;
        let baseline = 16 + row * 28 + 20;
        for ch in line.chars() {
            if ch == '\n' || ch == '\r' {
                continue;
            }
            if ch == '\t' {
                x += 48.;
                continue;
            }
            if ch.is_control() {
                continue;
            }
            if !ch.is_whitespace() && f.lookup_glyph_index(ch) == 0 {
                return fail(503, "OUTPUT_CJK_FONT_UNAVAILABLE");
            }
            let (m, bitmap) = f.rasterize(ch, 20.);
            let top = baseline as i32 - m.ymin - m.height as i32;
            let left = x as i32 + m.xmin;
            for dy in 0..m.height {
                for dx in 0..m.width {
                    let px = left + dx as i32;
                    let py = top + dy as i32;
                    if px >= 0 && px < width as i32 && py >= 0 && py < height as i32 {
                        let alpha = bitmap[dy * m.width + dx];
                        let p = py as usize * width + px as usize;
                        pixels[p] = ((pixels[p] as u16 * (255 - alpha) as u16) / 255) as u8;
                    }
                }
            }
            x += m.advance_width;
        }
    }
    let mut raw = vec![];
    let mut encoder = jpeg_encoder::Encoder::new(&mut raw, 60);
    encoder.set_optimized_huffman_tables(true);
    let metadata = format!(
        "777-output-v1\0{}\0{}",
        payload["job_id"].as_str().unwrap_or(""),
        hash(encoded(payload))
    );
    encoder
        .add_app_segment(15, metadata.as_bytes())
        .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    encoder
        .encode(
            &pixels,
            width as u16,
            height as u16,
            jpeg_encoder::ColorType::Luma,
        )
        .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    if raw.len() > LIMIT {
        return fail(413, "OUTPUT_TOO_LARGE");
    }
    Ok(raw)
}
