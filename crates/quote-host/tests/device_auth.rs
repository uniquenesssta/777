use quote_host::{auth::Auth, devices::Devices};
use quote_ledger::store::{uid, Actor};
use serde_json::{json, Value};
struct Fixture {
    root: std::path::PathBuf,
    auth: Auth,
    devices: Devices,
    admin: Actor,
    sales: String,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("777-device-test-{}", uid().unwrap()));
        std::fs::create_dir(&root).unwrap();
        let mut auth =
            Auth::create(&root.join("auth"), "manager", "isolated-long-password").unwrap();
        let v = auth
            .login(&json!("manager"), &json!("isolated-long-password"), "test")
            .unwrap();
        let admin = auth.authenticate(v["token"].as_str().unwrap()).unwrap();
        let sales = auth
            .create_account(
                &admin,
                &json!({"username":"sales-one","password":"isolated-long-password","role":"sales"}),
            )
            .unwrap()["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let devices = Devices::create(&root.join("devices")).unwrap();
        Self {
            root,
            auth,
            devices,
            admin,
            sales,
        }
    }
    fn grant(&self, subject: &str, kind: &str) -> Value {
        self.devices
            .issue(
                &self.auth,
                &self.admin,
                &json!({"subject":subject,"delivery":kind,"ttl_seconds":600}),
            )
            .unwrap()
    }
    fn request(&self, grant: &Value) -> Value {
        json!({"ticket":grant["ticket"],"delivery":grant["delivery"],"device_id":uid().unwrap(),"device_secret":"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"})
    }
    fn session(&self, request: &Value) -> Value {
        let mut v = request.clone();
        v.as_object_mut().unwrap().remove("ticket");
        self.devices.session(&self.auth, &v).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}
#[test]
fn enrollment_is_idempotent_only_for_the_original_persisted_device() {
    let f = Fixture::new();
    let g = f.grant(&f.sales, "sales");
    let r = f.request(&g);
    let a = f.devices.enroll(&f.auth, &r).unwrap();
    assert_eq!(a, f.devices.enroll(&f.auth, &r).unwrap());
    let mut other = r.clone();
    other["device_id"] = json!(uid().unwrap());
    assert!(f.devices.enroll(&f.auth, &other).is_err());
    other = r.clone();
    other["device_secret"] = json!("Z".repeat(43));
    assert!(f.devices.enroll(&f.auth, &other).is_err());
    let s = f.session(&r);
    assert_eq!(
        f.devices
            .authenticate(&f.auth, s["token"].as_str().unwrap())
            .unwrap()
            .subject,
        f.sales
    );
}
#[test]
fn manager_package_or_forged_role_does_not_elevate_sales() {
    let f = Fixture::new();
    assert!(f
        .devices
        .issue(
            &f.auth,
            &f.admin,
            &json!({"subject":f.sales,"delivery":"manager","ttl_seconds":600})
        )
        .is_err());
    let g = f.grant(&f.sales, "sales");
    let mut r = f.request(&g);
    r["role"] = json!("admin");
    assert!(f.devices.enroll(&f.auth, &r).is_err());
    r.as_object_mut().unwrap().remove("role");
    r["delivery"] = json!("manager");
    assert!(f.devices.enroll(&f.auth, &r).is_err());
}
#[test]
fn only_admin_can_issue_list_or_revoke_devices() {
    let f = Fixture::new();
    let a = Actor {
        subject: f.sales.clone(),
        role: "sales".into(),
    };
    assert!(f.devices.issue(&f.auth, &a, &json!({})).is_err());
    assert!(f.devices.listing(&a).is_err());
    assert!(f.devices.revoke(&a, &uid().unwrap()).is_err());
}
#[test]
fn revoke_one_device_invalidates_live_sessions_and_preserves_other_device() {
    let f = Fixture::new();
    let r1 = f.request(&f.grant(&f.sales, "sales"));
    let r2 = f.request(&f.grant(&f.sales, "sales"));
    f.devices.enroll(&f.auth, &r1).unwrap();
    f.devices.enroll(&f.auth, &r2).unwrap();
    let s1 = f.session(&r1);
    let s2 = f.session(&r2);
    f.devices
        .revoke(&f.admin, r1["device_id"].as_str().unwrap())
        .unwrap();
    assert!(f
        .devices
        .authenticate(&f.auth, s1["token"].as_str().unwrap())
        .is_err());
    assert!(f.devices.enroll(&f.auth, &r1).is_err());
    assert_eq!(
        f.devices
            .authenticate(&f.auth, s2["token"].as_str().unwrap())
            .unwrap()
            .subject,
        f.sales
    );
}
#[test]
fn expired_material_and_expired_sessions_cannot_authorize() {
    let f = Fixture::new();
    let g = f.grant(&f.sales, "sales");
    let r = f.request(&g);
    let c = rusqlite::Connection::open(&f.devices.path).unwrap();
    c.execute("UPDATE grants SET expires=0", []).unwrap();
    assert!(f.devices.enroll(&f.auth, &r).is_err());
    c.execute("UPDATE grants SET expires=9999999999", [])
        .unwrap();
    f.devices.enroll(&f.auth, &r).unwrap();
    let s = f.session(&r);
    c.execute("UPDATE device_sessions SET expires=0", [])
        .unwrap();
    assert!(f
        .devices
        .authenticate(&f.auth, s["token"].as_str().unwrap())
        .is_err());
    let renewed = f.session(&r);
    assert_eq!(renewed["subject"], f.sales);
}
#[test]
fn account_epoch_and_restore_invalidate_credentials_without_changing_actor() {
    let f = Fixture::new();
    let r = f.request(&f.grant(&f.sales, "sales"));
    f.devices.enroll(&f.auth, &r).unwrap();
    let s = f.session(&r);
    f.auth
        .update_account(
            &f.admin,
            &f.sales,
            &json!({"password":"replacement-long-secret"}),
        )
        .unwrap();
    assert!(f
        .devices
        .authenticate(&f.auth, s["token"].as_str().unwrap())
        .is_err());
    let r = f.request(&f.grant(&f.sales, "sales"));
    assert_eq!(f.devices.enroll(&f.auth, &r).unwrap()["subject"], f.sales);
    f.devices.revoke_all().unwrap();
    assert!(f.devices.enroll(&f.auth, &r).is_err());
}
#[test]
fn listings_and_audit_do_not_expose_grants_credentials_or_tokens() {
    let f = Fixture::new();
    let g = f.grant(&f.sales, "sales");
    let r = f.request(&g);
    f.devices.enroll(&f.auth, &r).unwrap();
    let s = f.session(&r);
    let listing = f.devices.listing(&f.admin).unwrap().to_string();
    for value in [&g["ticket"], &r["device_secret"], &s["token"]] {
        assert!(!listing.contains(value.as_str().unwrap()));
    }
    let raw = std::fs::read(&f.devices.path).unwrap();
    for value in [&g["ticket"], &r["device_secret"], &s["token"]] {
        assert!(!raw
            .windows(value.as_str().unwrap().len())
            .any(|w| w == value.as_str().unwrap().as_bytes()));
    }
}

#[test]
fn development_short_password_is_not_a_production_account_policy() {
    let f = Fixture::new();
    assert!(Auth::create(&f.root.join("short"), "admin", "123456").is_err());
    assert!(f
        .auth
        .create_account(
            &f.admin,
            &json!({"username":"new-admin","password":"123456","role":"admin"})
        )
        .is_err());
}
