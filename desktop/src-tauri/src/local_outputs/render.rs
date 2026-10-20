use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use fontdue::{Font, FontSettings};
use sha2::{Digest, Sha256};
use std::sync::{Arc, OnceLock};
static FONT: OnceLock<Arc<Font>> = OnceLock::new();
pub(crate) fn set_font(raw: &[u8]) -> Result<()> {
    if format!("{:x}", Sha256::digest(raw))
        != "d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964"
    {
        return Err(DesktopError::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"));
    }
    let f = Font::from_bytes(raw, FontSettings::default())
        .map_err(|_| DesktopError::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"))?;
    let _ = FONT.set(Arc::new(f));
    Ok(())
}
pub(super) fn font() -> Result<Arc<Font>> {
    if let Some(f) = FONT.get() {
        return Ok(f.clone());
    }
    #[cfg(debug_assertions)]
    {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../public/fonts/NotoSansSC-VF.ttf");
        if let Ok(raw) = std::fs::read(path) {
            set_font(&raw)?;
        }
    }
    FONT.get()
        .cloned()
        .ok_or_else(|| DesktopError::new(503, "OUTPUT_CJK_FONT_UNAVAILABLE"))
}
pub(crate) fn execute(store: &Store, scope: &str, id: &str) -> Result<Value> {
    let mut job = jobs::get(store, scope, id)?;
    let result = (|| {
        let payload = jobs::payload(store, id)?;
        let raw = if payload["kind"] == "quote_png" {
            super::image::render(&payload)?
        } else {
            quote_excel::write::write(&payload).map_err(|e| DesktopError::new(422, &e.code))?
        };
        let content = json!({"format":"777-output-v1","job_id":id,"size":raw.len(),"sha256":format!("{:x}",Sha256::digest(&raw)),"data_base64":STANDARD.encode(raw)});
        super::save(
            &root(store)?,
            id,
            payload["kind"].as_str().unwrap_or(""),
            &content,
        )
    })();
    match result {
        Ok(path) => {
            job["state"] = json!("done");
            job["local_path"] = json!(path.to_string_lossy());
            job["error"] = Value::Null;
        }
        Err(e) => {
            quote_diagnostics::event(
                "desktop.output.failed",
                json!({"job_id":id,"kind":job["kind"],"error":e.code}),
            );
            job["state"] = json!("failed");
            job["error"] = json!(e.code);
        }
    }
    jobs::update(store, scope, &job)?;
    Ok(job)
}
