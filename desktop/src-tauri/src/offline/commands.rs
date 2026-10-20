//! Stable local command receipts close the commit-to-renderer crash gap.
use super::*;
use rusqlite::{params, OptionalExtension};
impl Local {
    pub(crate) fn replay(&self, kind: &str, body: &Value) -> Result<Option<Value>> {
        let Some(id) = body["operation_id"].as_str() else {
            return Ok(None);
        };
        identifier(&body["operation_id"])?;
        let row: Option<(String, Vec<u8>, Vec<u8>)> = self
            .c
            .query_row(
                "SELECT subject,body,receipt FROM local_commands WHERE id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()
            .map_err(sql)?;
        if let Some((subject, stored, receipt)) = row {
            if self.context()?["binding"]["subject"] != subject
                || self.decode(&stored)? != json!({"kind":kind,"body":body})
            {
                return Err(fault("LOCAL_COMMAND_ID_CONFLICT"));
            }
            return Ok(Some(self.decode(&receipt)?));
        }
        Ok(None)
    }
    pub(super) fn remember_command(&self, kind: &str, body: &Value, result: &Value) -> Result<()> {
        if let Some(id) = body["operation_id"].as_str() {
            let subject = self.context()?["binding"]["subject"]
                .as_str()
                .ok_or_else(|| fault("LOCAL_DATA_INVALID"))?
                .to_owned();
            self.c
                .execute(
                    "INSERT INTO local_commands VALUES(?,?,?,?)",
                    params![
                        id,
                        subject,
                        self.encode(&json!({"kind":kind,"body":body}))?,
                        self.encode(result)?
                    ],
                )
                .map_err(sql)?;
        }
        Ok(())
    }
    pub(crate) fn saved_receipt(&self, id: &str) -> Result<Value> {
        let ctx = self.context()?;
        permit(&ctx, "quote")?;
        let row: Option<(String, Vec<u8>, Vec<u8>)> = self
            .c
            .query_row(
                "SELECT subject,body,receipt FROM local_commands WHERE id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()
            .map_err(sql)?;
        if let Some((subject, body, receipt)) = row {
            if ctx["binding"]["subject"] != subject {
                return Err(DesktopError::new(403, "LOCAL_COMMAND_OWNER_MISMATCH"));
            }
            let body = self.decode(&body)?;
            if !body["body"]["order_id"].is_null() {
                permit(&ctx, "edit_orders")?;
            }
            return Ok(json!({"result":self.decode(&receipt)?,"submitted":body["body"]}));
        }
        Ok(json!({"result":null,"submitted":null}))
    }
}
