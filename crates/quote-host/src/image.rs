use crate::{fail, files, Error, Result};
use fontdue::{Font, FontSettings};
use quote_ledger::store::{encoded, hash};
use serde_json::Value;
use std::{
    io::Cursor,
    path::Path,
    sync::{Arc, Mutex, OnceLock},
};
const LIMIT: usize = 4 * 1024 * 1024;
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
pub fn font(path: &Path) -> Result<Arc<Font>> {
    type CachedFont = Option<(std::path::PathBuf, Arc<Font>)>;
    static CACHE: OnceLock<Mutex<CachedFont>> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| Error::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"))?;
    if let Some((p, f)) = &*cache {
        if p == path {
            return Ok(f.clone());
        }
    }
    let raw = files::read(path, 64 * 1024 * 1024)?;
    let f = Arc::new(
        Font::from_bytes(raw, FontSettings::default())
            .map_err(|_| Error::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"))?,
    );
    *cache = Some((path.into(), f.clone()));
    Ok(f)
}
pub fn render(payload: &Value, font_path: Option<&Path>) -> Result<Vec<u8>> {
    let f = font(font_path.ok_or_else(|| Error::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"))?)?;
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
                    .chunks(40)
                    .map(|a| a.iter().collect())
                    .collect::<Vec<String>>()
            }
        })
        .collect::<Vec<_>>();
    if wrapped.len() > 400 {
        return fail(422, "OUTPUT_IMAGE_TOO_TALL");
    }
    let height = 40 + wrapped.len() * 36;
    let width = 1200;
    let mut pixels = vec![255u8; width * height * 3];
    for (row, line) in wrapped.iter().enumerate() {
        let mut x = 24f32;
        let baseline = 20 + row * 36 + 24;
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
            let (m, bitmap) = f.rasterize(ch, 24.);
            let top = baseline as i32 - m.ymin - m.height as i32;
            let left = x as i32 + m.xmin;
            for dy in 0..m.height {
                for dx in 0..m.width {
                    let px = left + dx as i32;
                    let py = top + dy as i32;
                    if px >= 0 && px < width as i32 && py >= 0 && py < height as i32 {
                        let alpha = bitmap[dy * m.width + dx];
                        let p = (py as usize * width + px as usize) * 3;
                        for c in &mut pixels[p..p + 3] {
                            *c = ((*c as u16 * (255 - alpha) as u16) / 255) as u8;
                        }
                    }
                }
            }
            x += m.advance_width;
        }
    }
    let mut raw = vec![];
    {
        let mut e = png::Encoder::new(&mut raw, width as u32, height as u32);
        e.set_color(png::ColorType::Rgb);
        e.set_depth(png::BitDepth::Eight);
        for (k, v) in [
            ("777_format", "777-output-v1".to_string()),
            (
                "777_job_id",
                payload["job_id"].as_str().unwrap_or("").to_string(),
            ),
            ("777_payload_sha256", hash(encoded(payload))),
        ] {
            e.add_text_chunk(k.into(), v)
                .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
        }
        let mut writer = e
            .write_header()
            .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
        writer
            .write_image_data(&pixels)
            .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    }
    if raw.len() > LIMIT {
        return fail(413, "OUTPUT_TOO_LARGE");
    }
    validate(&raw, payload)?;
    Ok(raw)
}
pub fn validate(raw: &[u8], payload: &Value) -> Result<()> {
    if raw.is_empty() || raw.len() > LIMIT {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    let mut d = png::Decoder::new(Cursor::new(raw));
    d.set_limits(png::Limits {
        bytes: 64 * 1024 * 1024,
    });
    let mut r = d
        .read_info()
        .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    let info = r.info();
    if info.width != 1200 || info.height > 14440 || info.height == 0 {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    let get = |key: &str| {
        info.uncompressed_latin1_text
            .iter()
            .find(|t| t.keyword == key)
            .map(|t| t.text.as_str())
    };
    let expected = hash(encoded(payload));
    if get("777_format") != Some("777-output-v1")
        || get("777_job_id") != payload["job_id"].as_str()
        || get("777_payload_sha256") != Some(expected.as_str())
    {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    let size = r
        .output_buffer_size()
        .ok_or_else(|| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    if size > 64 * 1024 * 1024 {
        return fail(422, "OUTPUT_BLOB_INVALID");
    }
    r.next_frame(&mut vec![0; size])
        .map_err(|_| Error::new(422, "OUTPUT_BLOB_INVALID"))?;
    Ok(())
}
