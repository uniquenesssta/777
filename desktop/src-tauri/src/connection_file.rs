//! Bounded native parsing. Private deployment material never crosses the webview boundary.
use crate::{Connection, DesktopError, Result};
use serde::{de::DeserializeOwned, Deserialize};
use std::{fs::File, io::Read, path::Path};

pub(crate) fn read<T: DeserializeOwned>(path: &str, schema: &str) -> Result<T> {
    let invalid = || DesktopError::new(422, "CONNECTION_FILE_INVALID");
    let p = Path::new(path);
    if !p.is_absolute() {
        return Err(invalid());
    }
    let f = File::open(p).map_err(|_| DesktopError::new(422, "CONNECTION_FILE_UNAVAILABLE"))?;
    if !f.metadata().map_err(|_| invalid())?.is_file() {
        return Err(invalid());
    }
    let mut bytes = Vec::new();
    f.take(65537)
        .read_to_end(&mut bytes)
        .map_err(|_| invalid())?;
    if bytes.len() > 65536 {
        return Err(invalid());
    }
    let bytes = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
    let value: serde_json::Value = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if value["schema"] != schema {
        return Err(DesktopError::new(422, "CONNECTION_FILE_WRONG_KIND"));
    }
    serde_json::from_value(value).map_err(|_| invalid())
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PublicConnection {
    schema: String,
    connection: Connection,
}
pub(crate) fn public(path: &str) -> Result<Connection> {
    let file: PublicConnection = read(path, "777-public-connection-v1")?;
    if file.schema != "777-public-connection-v1" {
        return Err(DesktopError::new(422, "CONNECTION_FILE_WRONG_KIND"));
    }
    crate::tls::build(&file.connection)?;
    Ok(file.connection)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn parser_rejects_private_material_wrong_kind_and_oversized_files() {
        let p = std::env::temp_dir().join(format!(
            "777-connection-{}.json",
            crate::types::new_id().unwrap()
        ));
        std::fs::write(
            &p,
            b"{\"schema\":\"777-desktop-bootstrap-v1\",\"ticket\":\"secret\"}",
        )
        .unwrap();
        assert_eq!(
            public(p.to_str().unwrap()).err().unwrap().code,
            "CONNECTION_FILE_WRONG_KIND"
        );
        std::fs::write(&p, vec![b' '; 65537]).unwrap();
        assert_eq!(
            public(p.to_str().unwrap()).err().unwrap().code,
            "CONNECTION_FILE_INVALID"
        );
        std::fs::write(&p,b"{\"schema\":\"777-public-connection-v1\",\"connection\":{},\"private_key\":\"secret\"}").unwrap();
        assert_eq!(
            public(p.to_str().unwrap()).err().unwrap().code,
            "CONNECTION_FILE_INVALID"
        );
        std::fs::remove_file(p).unwrap();
    }
}
