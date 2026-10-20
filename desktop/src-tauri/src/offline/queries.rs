use super::*;
impl Local {
    pub(super) fn all(&self) -> Result<Vec<Value>> {
        let ctx = self.context()?;
        let mut q = self
            .c
            .prepare("SELECT working FROM local_orders")
            .map_err(sql)?;
        let rows = q
            .query_map([], |r| r.get::<_, Vec<u8>>(0))
            .map_err(sql)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(sql)?;
        let mut out = Vec::new();
        for raw in rows {
            let mut v = self.decode(&raw)?;
            if let Some(alias) =
                self.meta(&format!("alias:{}", v["order_id"].as_str().unwrap_or("")))?
            {
                if let Some(id) = alias.as_str() {
                    if self
                        .c
                        .query_row(
                            "SELECT EXISTS(SELECT 1 FROM local_orders WHERE id=?)",
                            [id],
                            |r| r.get::<_, bool>(0),
                        )
                        .map_err(sql)?
                    {
                        continue;
                    }
                }
            }
            if ctx["binding"]["role"] == "admin" || v["owner_id"] == ctx["binding"]["subject"] {
                public(&mut v, &ctx);
                out.push(v)
            }
        }
        out.sort_by(|a, b| {
            b["created_at"]
                .as_str()
                .cmp(&a["created_at"].as_str())
                .then_with(|| b["order_id"].as_str().cmp(&a["order_id"].as_str()))
        });
        Ok(out)
    }
    pub(crate) fn listing(
        &self,
        query: &str,
        state: &str,
        offset: u32,
        view: &str,
    ) -> Result<Value> {
        permit(&self.context()?, "orders")?;
        if query.chars().count() > 256
            || !["", "active", "void"].contains(&state)
            || offset > 1000000
        {
            return Err(fault("INVALID_QUERY"));
        }
        let q = quote_core::search::casefold(query);
        let all = self
            .all()?
            .into_iter()
            .filter(|o| {
                (state.is_empty() || o["state"] == state)
                    && ["customer", "order_ref", "wechat"].iter().any(|k| {
                        quote_core::search::casefold(o["details"][k].as_str().unwrap_or(""))
                            .contains(&q)
                    })
            })
            .collect::<Vec<_>>();
        let token = quote_ledger::store::hash(
            serde_json::to_vec(&json!([
                query,
                state,
                all.iter()
                    .map(|o| json!([o["order_id"], o["revision"]]))
                    .collect::<Vec<_>>()
            ]))
            .map_err(json_error)?,
        );
        if !view.is_empty() && view != token {
            return Err(fault("QUERY_VIEW_CHANGED"));
        }
        Ok(
            json!({"orders":all.iter().skip(offset as usize).take(20).collect::<Vec<_>>(),"offset":offset,"limit":20,"total":all.len(),"totals":totals(&all)?,"view":token,"next_cursor":null}),
        )
    }
    pub(crate) fn customers(
        &self,
        query: &str,
        offset: u32,
        group: Option<&str>,
        order_offset: u32,
        identity: Option<&quote_core::customer_identity::CustomerIdentity>,
    ) -> Result<Value> {
        permit(&self.context()?, "orders")?;
        if identity.is_some_and(|v| !v.valid()) {
            return Err(fault("INVALID_QUERY"));
        }
        let q = quote_core::search::casefold(query);
        let mut groups: Vec<(String, Vec<Value>)> = Vec::new();
        for o in self.all()? {
            if identity.is_some_and(|v| {
                !v.matches(
                    o["details"]["customer"].as_str().unwrap_or(""),
                    o["details"]["wechat"].as_str().unwrap_or(""),
                )
            }) {
                continue;
            }
            if !["customer", "order_ref", "wechat"].iter().any(|k| {
                quote_core::search::casefold(o["details"][k].as_str().unwrap_or("")).contains(&q)
            }) {
                continue;
            }
            let id = o["customer_id"]
                .as_str()
                .unwrap_or(o["order_id"].as_str().unwrap())
                .to_owned();
            if group.is_some_and(|g| g != id) {
                continue;
            }
            if let Some((_, orders)) = groups.iter_mut().find(|(i, _)| i == &id) {
                orders.push(o)
            } else {
                groups.push((id, vec![o]));
            }
        }
        let total = groups.len();
        let mut out = Vec::new();
        for (id, orders) in groups.into_iter().skip(offset as usize).take(20) {
            out.push(json!({"group_id":id,"details":orders[0]["details"],"total":orders.len(),"active_count":orders.iter().filter(|o|o["state"]=="active").count(),"totals":totals(&orders)?,"orders":orders.iter().skip(order_offset as usize).take(20).collect::<Vec<_>>(),"order_offset":order_offset}));
        }
        Ok(json!({"groups":out,"total":total,"offset":offset,"limit":20}))
    }
}
fn totals(orders: &[Value]) -> Result<Value> {
    let mut out = json!({"income_cents":"0"});
    for k in ["income_cents", "cost_cents", "profit_cents"] {
        let mut sum = 0i64;
        let mut present = false;
        for o in orders.iter().filter(|o| o["state"] == "active") {
            if let Some(v) = o[k].as_str() {
                present = true;
                sum = sum
                    .checked_add(v.parse().map_err(|_| fault("LOCAL_DATA_INVALID"))?)
                    .ok_or_else(|| fault("AMOUNT_CAPACITY"))?
            }
        }
        if present {
            out[k] = json!(sum.to_string());
        }
    }
    Ok(out)
}
