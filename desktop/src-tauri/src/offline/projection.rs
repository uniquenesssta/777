//! Remove superseded private fields when an authenticated package loses finance.
use super::*;
use rusqlite::params;
impl Local {
    pub(super) fn narrow(&self, ctx: &Value) -> Result<()> {
        if permit(ctx, "finance").is_ok() {
            return Ok(());
        }
        self.c
            .execute("DELETE FROM local_diff_parts", [])
            .map_err(sql)?;
        self.put("history_download", &Value::Null)?;
        let rows = {
            let mut q = self
                .c
                .prepare("SELECT id,confirmed,working FROM local_orders")
                .map_err(sql)?;
            let rows = q
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<Vec<u8>>>(1)?,
                        r.get::<_, Vec<u8>>(2)?,
                    ))
                })
                .map_err(sql)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(sql)?;
            rows
        };
        for (id, confirmed, working) in rows {
            let mut working = self.decode(&working)?;
            public(&mut working, ctx);
            let confirmed = confirmed
                .map(|v| {
                    let mut v = self.decode(&v)?;
                    public(&mut v, ctx);
                    self.encode(&v)
                })
                .transpose()?;
            self.c
                .execute(
                    "UPDATE local_orders SET confirmed=?,working=? WHERE id=?",
                    params![confirmed, self.encode(&working)?, id],
                )
                .map_err(sql)?;
        }
        let rows = {
            let mut q = self
                .c
                .prepare("SELECT order_id,revision,before,after FROM local_history")
                .map_err(sql)?;
            let rows = q
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, i64>(1)?,
                        r.get::<_, Vec<u8>>(2)?,
                        r.get::<_, Vec<u8>>(3)?,
                    ))
                })
                .map_err(sql)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(sql)?;
            rows
        };
        for (id, rev, a, b) in rows {
            let mut a = self.decode(&a)?;
            let mut b = self.decode(&b)?;
            public(&mut a, ctx);
            public(&mut b, ctx);
            self.c
                .execute(
                    "UPDATE local_history SET before=?,after=? WHERE order_id=? AND revision=?",
                    params![self.encode(&a)?, self.encode(&b)?, id, rev],
                )
                .map_err(sql)?;
        }
        let rows = {
            let mut q=self.c.prepare("SELECT key,value FROM local_meta WHERE key LIKE 'price:%' OR key LIKE 'diff:%' OR key='download'").map_err(sql)?;
            let rows = q
                .query_map([], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?))
                })
                .map_err(sql)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(sql)?;
            rows
        };
        for (key, raw) in rows {
            let mut v = self.decode(&raw)?;
            public(&mut v, ctx);
            self.put(&key, &v)?;
        }
        Ok(())
    }
}
