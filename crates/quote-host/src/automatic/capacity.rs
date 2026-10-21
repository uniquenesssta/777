//! Service-wide resource bounds; package fields no longer cap reuse on other computers.
use super::*;
pub(super) const DEVICES: i64 = 4096;
pub(super) const NODES: i64 = 128;
pub(super) fn device(c: &Connection) -> Result<()> {
    let total: i64 = c.query_row("SELECT count(*) FROM automatic_devices", [], |r| r.get(0))?;
    if total >= DEVICES {
        return fail(403, "DEVICE_ENROLLMENT_CAPACITY");
    }
    Ok(())
}
pub(super) fn node(c: &Connection) -> Result<()> {
    let total: i64 = c.query_row("SELECT count(*) FROM automatic_nodes", [], |r| r.get(0))?;
    if total >= NODES {
        return fail(403, "NODE_ENROLLMENT_CAPACITY");
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn service_bounds_still_reject_new_entries_at_capacity() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE automatic_devices(id INTEGER); CREATE TABLE automatic_nodes(id INTEGER);
            WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<4095) INSERT INTO automatic_devices SELECT x FROM n;
            WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<127) INSERT INTO automatic_nodes SELECT x FROM n;").unwrap();
        device(&c).unwrap();
        node(&c).unwrap();
        c.execute("INSERT INTO automatic_devices VALUES(4096)", [])
            .unwrap();
        c.execute("INSERT INTO automatic_nodes VALUES(128)", [])
            .unwrap();
        assert_eq!(device(&c).unwrap_err().code, "DEVICE_ENROLLMENT_CAPACITY");
        assert_eq!(node(&c).unwrap_err().code, "NODE_ENROLLMENT_CAPACITY");
    }
}
