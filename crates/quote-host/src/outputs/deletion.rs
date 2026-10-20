//! Failed job removal is persisted as an append-only event; receipts remain recoverable.
use super::*;

impl Outputs {
    pub fn delete_failed(&self, actor: &Actor, key: &str, request_id: &str) -> Result<Value> {
        id(request_id)?;
        let fingerprint = hash(encoded(
            &json!({"actor":actor.subject,"job_id":key,"operation":"delete"}),
        ));
        if let Some(value) = self.receipt(actor, request_id, Some(&fingerprint))? {
            return Ok(value);
        }
        let mut connection = self.connection()?;
        let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        self.owned(&tx, actor, key)?;
        let state: String =
            tx.query_row("SELECT state FROM jobs WHERE job_id=?", [key], |r| r.get(0))?;
        if state != "failed" {
            return fail(409, "OUTPUT_DELETE_FAILED_ONLY");
        }
        if !tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM events WHERE job_id=? AND operation='delete')",
            [key],
            |r| r.get::<_, bool>(0),
        )? {
            tx.execute(
                "INSERT INTO events(job_id,operation,actor_id,at) VALUES(?,'delete',?,?)",
                params![key, actor.subject, store::now()],
            )?;
        }
        let value =
            json!({"request_id":request_id,"job_id":key,"deleted":true,"format":"777-output-v1"});
        tx.execute(
            "INSERT INTO receipts VALUES(?,?,?,?)",
            params![request_id, actor.subject, fingerprint, encoded(&value)],
        )?;
        tx.commit()?;
        Ok(value)
    }
}
