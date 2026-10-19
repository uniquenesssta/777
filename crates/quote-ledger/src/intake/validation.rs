use super::*;
fn wire(v: &Value) -> Result<()> {
    match v {
        Value::Number(_) => return Err(Error::new("INVALID_DATABASE")),
        Value::Object(m) => {
            for (k, v) in m {
                if !k.is_ascii() {
                    return Err(Error::new("INVALID_DATABASE"));
                }
                wire(v)?;
            }
        }
        Value::Array(a) => {
            for v in a {
                wire(v)?;
            }
        }
        _ => (),
    };
    Ok(())
}
pub(super) fn originals(c: &Connection) -> Result<()> {
    let mut st=c.prepare("SELECT operation_id,stream_id,device_sequence,order_id,owner_id,kind,content_sha256,operation_json,previous_operation_id FROM offline_operations")?;
    let mut rows = st.query([])?;
    while let Some(row) = rows.next()? {
        let raw: String = row.get(7)?;
        let mut v: Value = serde_json::from_str(&raw)?;
        wire(&v)?;
        for (k, col) in [
            ("operation_id", 0),
            ("stream_id", 1),
            ("order_id", 3),
            ("owner_id", 4),
            ("kind", 5),
        ] {
            if v[k] != row.get::<_, String>(col)? {
                return Err(Error::new("INVALID_DATABASE"));
            }
        }
        if v["device_sequence"].as_str() != Some(row.get::<_, i64>(2)?.to_string().as_str())
            || v["base"]["previous_operation_id"]
                != serde_json::to_value(row.get::<_, Option<String>>(8)?)?
        {
            return Err(Error::new("INVALID_DATABASE"));
        }
        let sha: String = row.get(6)?;
        if v["content_sha256"] != sha {
            return Err(Error::new("INVALID_DATABASE"));
        }
        v.as_object_mut()
            .ok_or_else(|| Error::new("INVALID_DATABASE"))?
            .remove("content_sha256");
        let mut bytes = b"777-offline-order-v1\n".to_vec();
        bytes.extend(super::canonical::encode(&v).map_err(|_| Error::new("INVALID_DATABASE"))?);
        if store::hash(bytes) != sha {
            return Err(Error::new("INVALID_DATABASE"));
        }
    }
    Ok(())
}
