use quote_host::{auth, casefold, files, outputs, protocol};
use quote_ledger::store::Actor;
use serde_json::json;
struct Temp(std::path::PathBuf);
impl Temp {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "777-p06-host-test-{}",
            quote_ledger::store::uid().unwrap()
        ));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[test]
fn nested_duplicate_json_bad_unicode_and_nonfinite_are_rejected() {
    for raw in [
        br#"{"a":{"x":1,"x":2}}"#.as_slice(),
        br#"{"a":"\ud800"}"#,
        br#"{"a":NaN}"#,
        br#"{"a":Infinity}"#,
    ] {
        assert!(protocol::decode(raw, 1024).is_err());
    }
    assert_eq!(
        protocol::decode(br#"{"n":9007199254740993}"#, 1024).unwrap()["n"].to_string(),
        "9007199254740993"
    );
    assert_eq!(
        protocol::decode(&vec![b' '; 1025], 1024)
            .unwrap_err()
            .status,
        413
    );
}
#[test]
fn native_scrypt_matches_accepted_python_verifier() {
    let out = auth::verifier("fixture-secret-123", b"0123456789abcdef").unwrap();
    let s = out.iter().map(|b| format!("{b:02x}")).collect::<String>();
    assert_eq!(
        s,
        "94be1178dd7ed065196d0bc204d04242cd99b036747edc6a56c995219c0aa117"
    );
}
#[test]
fn username_and_search_share_full_unicode_casefold() {
    assert_eq!(casefold("Straße Σς İ ﬀ"), "strasse σσ i\u{307} ff");
    assert_eq!(
        auth::username(&json!("STRASSE")).unwrap(),
        auth::username(&json!("Straße")).unwrap()
    );
    assert!(auth::username(&json!(" spaced")).is_err());
}
#[test]
fn sales_projection_is_an_allowlist_and_exact_cents_stay_strings() {
    let a = Actor {
        subject: "sale".into(),
        role: "sales".into(),
    };
    let v = protocol::financial(
        json!({"income_cents":"9007199254740993","cost_cents":"4","profit_cents":"1","owner_id":"x","future_private":{"cost":7}}),
        &a,
    );
    assert_eq!(v, json!({"income_cents":"9007199254740993"}));
}
#[test]
fn public_quote_input_cannot_claim_actor_totals_or_boolean_numbers() {
    for v in [
        json!({"price_version_id":"v","lines":[{"line_kind":"normal","product_id":"p","q":true}]}),
        json!({"price_version_id":"v","lines":[],"actor":"admin"}),
        json!({"price_version_id":"v","lines":[{"line_kind":"discount","percent":"90","income_cents":"1"}]}),
    ] {
        assert!(protocol::quote(&v).is_err())
    }
}
#[test]
fn protected_dacl_requires_exact_inheritable_allowlist() {
    let allowed = vec![
        "S-1-5-18".into(),
        "S-1-5-32-544".into(),
        "S-1-5-21-1-2-3-1001".into(),
    ];
    let good = "D:PAI(A;OICI;FA;;;SY)(A;CIOI;0x1f01ff;;;BA)(A;OICI;FA;;;S-1-5-21-1-2-3-1001)";
    files::verify_dacl(good, &allowed, None).unwrap();
    for bad in [
        good.replace("PAI", "AI"),
        good.replace("OICI;FA;;;SY", ";FA;;;SY"),
        good.replace("S-1-5-21-1-2-3-1001", "S-1-1-0"),
        format!("{good}(A;OICI;FA;;;WD)"),
    ] {
        assert!(files::verify_dacl(&bad, &allowed, None).is_err())
    }
}
#[test]
fn native_ace_identity_resolves_display_aliases_without_widening_the_allowlist() {
    let allowed = vec![
        "S-1-5-18".into(),
        "S-1-5-32-544".into(),
        "S-1-5-21-1-2-3-500".into(),
    ];
    let display = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;LA)";
    // The old display-only policy cannot identify a machine-relative alias.
    assert!(files::verify_dacl(display, &allowed, None).is_err());
    files::verify_dacl(display, &allowed, Some(&allowed)).unwrap();
    for identities in [
        vec![
            allowed[0].clone(),
            allowed[1].clone(),
            "S-1-5-21-9-8-7-500".into(),
        ],
        vec![allowed[0].clone(), allowed[1].clone(), allowed[0].clone()],
        allowed[..2].to_vec(),
    ] {
        assert!(files::verify_dacl(display, &allowed, Some(&identities)).is_err());
    }
    for invalid in [
        display.replace("PAI", "AI"),
        display.replace("OICI;FA;;;LA", "OICI;FR;;;LA"),
        display.replace("OICI;FA;;;LA", "OICIID;FA;;;LA"),
        format!("{display}(A;OICI;FA;;;WD)"),
    ] {
        assert!(files::verify_dacl(&invalid, &allowed, Some(&allowed)).is_err());
    }
}
#[test]
fn exclusive_publish_preserves_an_existing_target_and_rejects_different_bytes() {
    let t = Temp::new();
    let source = t.0.join("source");
    let target = t.0.join("target");
    std::fs::write(&source, b"new").unwrap();
    std::fs::write(&target, b"original").unwrap();
    assert!(files::publish_new(&source, &target).is_err());
    assert_eq!(std::fs::read(&target).unwrap(), b"original");
    assert!(outputs::publish(&source, &t.0, "target", &quote_ledger::store::hash(b"new")).is_err());
    assert_eq!(std::fs::read(&target).unwrap(), b"original");
}
#[test]
fn same_host_owner_lock_excludes_second_native_instance() {
    let t = Temp::new();
    let owner = files::Owner::acquire(&t.0).unwrap();
    assert!(files::Owner::acquire(&t.0).is_err());
    drop(owner);
    files::Owner::acquire(&t.0).unwrap();
}
#[test]
fn native_auth_original_schema_rejects_extra_trigger_without_repair() {
    let t = Temp::new();
    let p = t.0.join("auth.sqlite3");
    let a = auth::Auth::create(&p, "manager", "fixture-secret-123").unwrap();
    let c = a.connection().unwrap();
    c.execute_batch("CREATE TRIGGER unknown BEFORE UPDATE ON users BEGIN SELECT 1; END")
        .unwrap();
    drop(c);
    assert!(a.connection().is_err());
    let c = rusqlite::Connection::open(&p).unwrap();
    assert_eq!(
        c.query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='unknown'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
}
#[test]
fn png_without_approved_readable_font_fails_explicitly() {
    let p = json!({"kind":"quote_png"});
    assert_eq!(
        quote_host::image::render(&p, None).unwrap_err().code,
        "OUTPUT_CJK_FONT_UNAVAILABLE"
    );
}

#[cfg(unix)]
#[test]
fn selected_directory_alias_writes_and_shares_the_same_owner_lock() {
    let temp = Temp::new();
    let actual = temp.0.join("actual");
    let alias = temp.0.join("selected alias");
    std::fs::create_dir(&actual).unwrap();
    std::fs::create_dir(actual.join(".777-path-check")).unwrap();
    std::fs::create_dir(actual.join(".777-parent-check")).unwrap();
    std::os::unix::fs::symlink(&actual, &alias).unwrap();
    files::writable_directory(&alias).unwrap();
    files::new_file(&alias.join("keep.txt"), b"original").unwrap();
    assert_eq!(std::fs::read(actual.join("keep.txt")).unwrap(), b"original");
    let owner = files::Owner::acquire(&alias).unwrap();
    assert!(files::Owner::acquire(&actual).is_err());
    std::os::unix::fs::symlink(actual.join("keep.txt"), alias.join("file-link")).unwrap();
    assert!(files::read(&alias.join("file-link"), 100).is_err());
    drop(owner);
    assert!(files::Owner::acquire(&actual).is_ok());
}
