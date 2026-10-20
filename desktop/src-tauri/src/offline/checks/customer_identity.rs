use super::*;
use quote_core::customer_identity::CustomerIdentity;
#[test]
fn offline_quote_matching_uses_the_same_identity_fields() {
    let f = Fixture::new();
    let body = f.body();
    f.local.save("save", &body).unwrap();
    for (customer, wechat, count) in [
        ("buyer", "", 1),
        ("", "contact", 1),
        ("buyer", "contact", 1),
        ("order-one", "", 0),
        ("contact", "", 0),
        ("", "buyer", 0),
        ("buy", "", 0),
        ("", "", 0),
    ] {
        let identity = CustomerIdentity {
            customer: customer.into(),
            wechat: wechat.into(),
        };
        assert_eq!(
            f.local.customers("", 0, None, 0, Some(&identity)).unwrap()["total"],
            count
        );
    }
}
