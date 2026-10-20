use quote_host::{auth::Auth, outputs::Outputs, query::Queries, recovery, service::Service};
use quote_ledger::{integrity, store};
use serde_json::{json, Value};
struct Fixture {
    root: std::path::PathBuf,
    s: Service,
    token: String,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("777-edit-{}", store::uid().unwrap()));
        let private = root.join("private");
        std::fs::create_dir_all(&private).unwrap();
        let ledger = private.join("ledger.sqlite3");
        let meta = store::create(&ledger).unwrap();
        let mut auth = Auth::create(
            &private.join("auth.sqlite3"),
            "manager",
            "fixture-secret-123",
        )
        .unwrap();
        let token = auth
            .login(&json!("manager"), &json!("fixture-secret-123"), "test")
            .unwrap()["token"]
            .as_str()
            .unwrap()
            .into();
        let outputs = Outputs::create(
            &private.join("outputs.sqlite3"),
            meta["ledger_id"].as_str().unwrap(),
        )
        .unwrap();
        let s = Service {
            root: root.clone(),
            ledger,
            config: json!({}),
            auth,
            outputs: Some(outputs),
            devices: None,
            queries: Queries::new().unwrap(),
            auxiliary: !cfg!(windows),
            font: None,
            test_fault: None,
        };
        Self { root, s, token }
    }
    fn post(&mut self, path: &str, data: Value) -> Value {
        self.s
            .handle("POST", path, &self.token, &data, "", "test")
            .unwrap()
    }
    fn get(&mut self, path: &str) -> Value {
        self.s
            .handle("GET", path, &self.token, &Value::Null, "", "test")
            .unwrap()
    }
    fn prices(&mut self, id: &str, old: Value, sale: &str) {
        self.post("/v1/prices",json!({"request_id":store::uid().unwrap(),"expected_price_version_id":old,"prices":{"price_version_id":id,"items":[{"product_id":"P","sale":sale,"cost":"4","k":"1","single":true}]}}));
    }
    fn output(&mut self, data: Value) -> Value {
        let v = self.post("/v1/outputs", data);
        self.drain();
        v
    }
    fn drain(&self) {
        while let Some(w) = self.s.prepare_output().unwrap() {
            let out = w.execute();
            self.s.outputs.as_ref().unwrap().finish(&w, out).unwrap();
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn draft(version: &str, number: &str) -> Value {
    json!({"request_id":store::uid().unwrap(),"order_id":null,"expected_revision":null,"sources":[null],"snapshot":{"price_version_id":version,"lines":[{"line_kind":"normal","product_id":"P","q":"1","h":"","w":"","name":""}],"rule_version":"business-v1","numeric_profile":"numeric-v1"},"details":{"customer":"淘宝0001","order_ref":number,"wechat":"wx0001"},"customer":{}})
}
#[test]
fn editing_keeps_prices_revisions_customer_groups_old_exports_and_recoverable_backup() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    let first = f.post("/v1/order-save", draft("v1", "00001"));
    let id = first["order_id"].as_str().unwrap().to_string();
    let old = f.get(&format!("/v1/orders/{id}"));
    let output=f.output(json!({"request_id":store::uid().unwrap(),"order_id":id,"expected_revision":1,"kind":"excel_admin"}));
    assert_eq!(
        f.get(&format!(
            "/v1/outputs/{}",
            output["job_id"].as_str().unwrap()
        ))["state"],
        "done"
    );
    f.prices("v2", json!("v1"), "20");
    let mut second = draft("v2", "00002");
    second["customer"] = json!({"customer_id":first["customer_id"]});
    f.post("/v1/order-save", second);
    let mut edit = draft("v2", "00001");
    edit["order_id"] = json!(id);
    edit["expected_revision"] = json!(1);
    edit["sources"] = json!([old["lines"][0]["line_id"], null, null]);
    edit["snapshot"]["lines"] = json!([old["lines"][0]["raw"],old["lines"][0]["raw"],{"line_kind":"discount","percent":"90","name":"折扣"}]);
    edit["customer"] = json!({"customer_id":first["customer_id"]});
    let saved = f.post("/v1/order-save", edit.clone());
    assert_eq!(saved["income_cents"], "2700");
    assert_eq!(saved["revision"], 2);
    assert_eq!(f.post("/v1/order-save", edit.clone()), saved);
    edit["request_id"] = json!(store::uid().unwrap());
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &f.token, &edit, "", "test")
        .is_err());
    let current = f.get(&format!("/v1/orders/{id}"));
    assert_eq!(current["lines"][0]["normalized"]["sale"], "10");
    assert_eq!(current["lines"][1]["normalized"]["sale"], "20");
    assert_eq!(current["history"][0]["income_cents"], "1000");
    let groups = f.post("/v1/customer-orders", json!({"query":"wx0001","offset":0}));
    assert_eq!(groups["total"], 1);
    assert_eq!(groups["groups"][0]["total"], 2);
    assert_eq!(groups["groups"][0]["totals"]["income_cents"], "4700");
    assert_eq!(
        groups["groups"][0]["orders"][0]["details"]["customer"],
        "淘宝0001"
    );
    let inventory = integrity::inventory(&store::open(&f.s.ledger, false).unwrap()).unwrap();
    assert_eq!(inventory["counts"]["orders"], 2);
    assert_eq!(inventory["active_income_cents"], "4700");
    assert_eq!(inventory["counts"]["order_versions"], 1);
    let year = time::OffsetDateTime::now_utc().year();
    let report=f.post("/v1/outputs/report",json!({"request_id":store::uid().unwrap(),"from":format!("{year}-01-01"),"to":format!("{year}-12-31")}));
    f.drain();
    assert_eq!(
        f.get(&format!(
            "/v1/outputs/{}",
            report["job_id"].as_str().unwrap()
        ))["state"],
        "done"
    );
    let data = recovery::capture(&f.s, "2026-10-17").unwrap();
    let encoded = recovery::encode(&data).unwrap();
    let decoded = recovery::decode(&encoded).unwrap();
    let restored = f.root.join("restored.sqlite3");
    recovery::restore_ledger(&decoded, &restored).unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&restored, false).unwrap()).unwrap(),
        inventory
    );
    let excel = quote_excel::backup::write(&serde_json::to_value(data).unwrap()).unwrap();
    let read = quote_excel::read::read(&excel).unwrap();
    assert_eq!(read.sheets[0].name, "阅读说明");
    assert!(read
        .sheets
        .iter()
        .any(|s| s.cells.iter().any(|c| c.value.as_deref() == Some("47.00"))));
    // Existing files remain bound to their original version after edits.
    f.s.outputs
        .as_ref()
        .unwrap()
        .validate_ledger(&restored)
        .unwrap();
}
#[test]
fn migration_preserves_v1_readonly_and_unknown_schema_is_not_repaired() {
    let root = std::env::temp_dir().join(format!("777-migrate-{}", store::uid().unwrap()));
    std::fs::create_dir(&root).unwrap();
    let path = root.join("v1");
    store::create_version(&path, true).unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&path, false).unwrap()).unwrap()["schema_version"],
        1
    );
    assert_eq!(
        integrity::inventory(&store::open(&path, true).unwrap()).unwrap()["schema_version"],
        2
    );
    let c = store::open(&path, true).unwrap();
    c.execute_batch("CREATE TABLE unknown(x TEXT)").unwrap();
    drop(c);
    assert!(store::open(&path, true).is_err());
    assert!(rusqlite::Connection::open(&path)
        .unwrap()
        .prepare("SELECT * FROM unknown")
        .is_ok());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn customer_choice_ambiguity_permissions_and_bad_sources_are_atomic() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    let first = f.post("/v1/order-save", draft("v1", "a"));
    let ambiguous = draft("v1", "b");
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &f.token, &ambiguous, "", "test")
        .is_err());
    let mut duplicate = draft("v1", "a");
    duplicate["customer"] = json!({"customer_id":first["customer_id"]});
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &f.token, &duplicate, "", "test")
        .is_err());
    let mut conflict = draft("v1", "b");
    conflict["customer"] = json!({"customer_id":first["customer_id"]});
    conflict["details"]["wechat"] = json!("different");
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &f.token, &conflict, "", "test")
        .is_err());
    f.post(
        "/v1/accounts",
        json!({"username":"sales","password":"fixture-secret-123","role":"sales"}),
    );
    let sales =
        f.s.auth
            .login(&json!("sales"), &json!("fixture-secret-123"), "sales")
            .unwrap()["token"]
            .as_str()
            .unwrap()
            .to_string();
    let listing =
        f.s.handle(
            "POST",
            "/v1/customer-orders",
            &sales,
            &json!({"query":"wx0001","offset":0}),
            "",
            "test",
        )
        .unwrap();
    assert_eq!(listing["total"], 0);
    let mut forgery = draft("v1", "b");
    forgery["customer"] = json!({"customer_id":first["customer_id"]});
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &sales, &forgery, "", "test")
        .is_err());
    assert!(f
        .s
        .handle(
            "POST",
            "/v1/outputs/report",
            &sales,
            &json!({"request_id":store::uid().unwrap(),"from":"2026-01-01","to":"2026-12-31"}),
            "",
            "test"
        )
        .is_err());
    let own =
        f.s.handle(
            "POST",
            "/v1/order-save",
            &sales,
            &draft("v1", "b"),
            "",
            "test",
        )
        .unwrap();
    assert!(own.get("cost_cents").is_none());
    let listing =
        f.s.handle(
            "POST",
            "/v1/customer-orders",
            &sales,
            &json!({"query":"wx0001","offset":0}),
            "",
            "test",
        )
        .unwrap();
    assert_eq!(listing["total"], 1);
    assert!(!listing.to_string().contains("cost_cents"));
    assert_eq!(
        listing["groups"][0]["orders"][0]["details"]["order_ref"],
        "b"
    );
    let order = f.get(&format!(
        "/v1/orders/{}",
        first["order_id"].as_str().unwrap()
    ));
    let mut bad = draft("v1", "a");
    bad["order_id"] = first["order_id"].clone();
    bad["expected_revision"] = json!(1);
    bad["sources"] = json!([store::uid().unwrap()]);
    assert!(f
        .s
        .handle("POST", "/v1/order-save", &f.token, &bad, "", "test")
        .is_err());
    assert_eq!(
        f.get(&format!(
            "/v1/orders/{}",
            first["order_id"].as_str().unwrap()
        )),
        order
    );
    let inventory = integrity::inventory(&store::open(&f.s.ledger, false).unwrap()).unwrap();
    assert_eq!(inventory["counts"]["orders"], 2);
    assert_eq!(inventory["counts"]["order_versions"], 0);
}

#[test]
fn differences_are_historical_positioned_and_permission_filtered() {
    let mut f = Fixture::new();
    f.prices("v1", Value::Null, "10");
    let first = f.post("/v1/order-save", draft("v1", "001"));
    let id = first["order_id"].as_str().unwrap().to_owned();
    let old = f.get(&format!("/v1/orders/{id}"));
    let mut edit = draft("v1", "001");
    edit["order_id"] = json!(id);
    edit["expected_revision"] = json!(1);
    edit["customer"] = json!({"customer_id":first["customer_id"]});
    edit["sources"] = json!([old["lines"][0]["line_id"], null]);
    let mut line = old["lines"][0]["raw"].clone();
    line["q"] = json!("2");
    edit["snapshot"]["lines"] = json!([line,{"line_kind":"discount","percent":"90","name":"折扣"}]);
    f.post("/v1/order-save", edit.clone());
    let diff = f.get(&format!("/v1/orders/{id}/changes/1"));
    assert_eq!(diff["to_revision"], "2");
    let changes = diff["changes"].as_array().unwrap();
    assert!(changes
        .iter()
        .any(|c| c["field"] == "数量" && c["before"] == "1" && c["after"] == "2"));
    assert!(changes.iter().any(|c| c["section"] == "第 2 项（新增）"
        && c["field"] == "顺序折扣（%）"
        && c["after"] == "90"));
    assert!(changes
        .iter()
        .any(|c| c["section"] == "订单合计" && c["field"] == "收入" && c["after"] == "1800"));
    // An intervening note increments the order revision without changing lines.
    f.post("/v1/notes",json!({"request_id":store::uid().unwrap(),"order_id":id,"expected_revision":2,"body":"备注"}));
    let current = f.get(&format!("/v1/orders/{id}"));
    edit["request_id"] = json!(store::uid().unwrap());
    edit["expected_revision"] = json!(3);
    edit["sources"] = json!([current["lines"][0]["line_id"]]);
    edit["snapshot"]["lines"] = json!([old["lines"][0]["raw"]]);
    f.post("/v1/order-save", edit);
    assert_eq!(f.get(&format!("/v1/orders/{id}/changes/1")), diff);
    let deletion = f.get(&format!("/v1/orders/{id}/changes/3"));
    assert!(deletion["changes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|c| c["section"] == "第 2 项（删除）" && c["after"].is_null()));
    let c = store::open(&f.s.ledger, false).unwrap();
    let owner: String = c
        .query_row("SELECT owner_id FROM orders WHERE order_id=?", [&id], |r| {
            r.get(0)
        })
        .unwrap();
    drop(c);
    // A different sales owner cannot read the manager's history. The sales
    // owner's own history below contains only public financial fields.
    f.post(
        "/v1/accounts",
        json!({"username":"sales-diff","password":"fixture-secret-123","role":"sales"}),
    );
    let sales =
        f.s.auth
            .login(&json!("sales-diff"), &json!("fixture-secret-123"), "sales")
            .unwrap()["token"]
            .as_str()
            .unwrap()
            .to_owned();
    assert!(f
        .s
        .handle(
            "GET",
            &format!("/v1/orders/{id}/changes/1"),
            &sales,
            &Value::Null,
            "",
            "test"
        )
        .is_err());
    assert!(!owner.is_empty());
    f.token = sales;
    let own = f.post("/v1/order-save", draft("v1", "sales-order"));
    let own_id = own["order_id"].as_str().unwrap();
    let before = f.get(&format!("/v1/orders/{own_id}"));
    let mut edit = draft("v1", "sales-order");
    edit["order_id"] = json!(own_id);
    edit["expected_revision"] = json!(1);
    edit["sources"] = json!([before["lines"][0]["line_id"]]);
    edit["snapshot"]["lines"][0]["q"] = json!("3");
    edit["customer"] = json!({"customer_id":own["customer_id"]});
    f.post("/v1/order-save", edit);
    let sales_diff = f.get(&format!("/v1/orders/{own_id}/changes/1"));
    let raw = serde_json::to_string(&sales_diff).unwrap();
    for forbidden in ["成本", "利润", "\"K\"", "cost_cents", "profit_cents"] {
        assert!(!raw.contains(forbidden));
    }
    assert!(sales_diff["changes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|c| c["field"] == "数量" && c["after"] == "3"));
}

#[test]
fn discount_policy_survives_publish_edit_reorder_and_backup() {
    let mut f = Fixture::new();
    let publish = |version: &str, old: Value, eligible: bool| json!({"request_id":store::uid().unwrap(),"expected_price_version_id":old,"prices":{"price_version_id":version,"items":[{"product_id":"P","sale":"100","cost":"40","k":"1","single":true,"discount_eligible":eligible}]}});
    f.post("/v1/prices", publish("v1", Value::Null, false));
    assert_eq!(f.get("/v1/prices")["items"][0]["discount_eligible"], false);
    let mut input = draft("v1", "policy");
    let normal = input["snapshot"]["lines"][0].clone();
    let discount = json!({"line_kind":"discount","percent":"50%","name":""});
    input["snapshot"]["lines"] = json!([normal, discount]);
    input["sources"] = json!([null, null]);
    let receipt = f.post("/v1/order-save", input);
    assert_eq!(receipt["income_cents"], "10000");
    let id = receipt["order_id"].as_str().unwrap();
    let old = f.get(&format!("/v1/orders/{id}"));
    assert_eq!(old["lines"][0]["normalized"]["discount_eligible"], "false");
    f.post("/v1/prices", publish("v2", json!("v1"), true));
    let mut edit = draft("v2", "policy");
    edit["order_id"] = json!(id);
    edit["expected_revision"] = json!(1);
    edit["customer"] = json!({"customer_id":receipt["customer_id"]});
    edit["snapshot"]["lines"] = json!([normal, normal, discount]);
    edit["sources"] = json!([old["lines"][0]["line_id"], null, old["lines"][1]["line_id"]]);
    let saved = f.post("/v1/order-save", edit);
    assert_eq!(saved["income_cents"], "15000");
    let current = f.get(&format!("/v1/orders/{id}"));
    let mut reordered = draft("v2", "policy");
    reordered["order_id"] = json!(id);
    reordered["expected_revision"] = json!(2);
    reordered["customer"] = json!({"customer_id":receipt["customer_id"]});
    reordered["snapshot"]["lines"] = json!([discount, normal, normal]);
    reordered["sources"] = json!([
        current["lines"][2]["line_id"],
        current["lines"][0]["line_id"],
        current["lines"][1]["line_id"]
    ]);
    assert_eq!(f.post("/v1/order-save", reordered)["income_cents"], "20000");
    let data = recovery::capture(&f.s, "2026-10-20").unwrap();
    let restored = f.root.join("discount-restored.sqlite3");
    recovery::restore_ledger(
        &recovery::decode(&recovery::encode(&data).unwrap()).unwrap(),
        &restored,
    )
    .unwrap();
    assert_eq!(
        integrity::inventory(&store::open(&restored, false).unwrap()).unwrap(),
        integrity::inventory(&store::open(&f.s.ledger, false).unwrap()).unwrap()
    );
}

#[path = "customer_order_checks/export_cleanup.rs"]
mod export_cleanup;
