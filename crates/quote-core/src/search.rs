//! Frozen identifier search folding shared by Host and native local queries.
pub fn casefold(s: &str) -> String {
    use std::{collections::BTreeMap, sync::OnceLock};
    static DATA: OnceLock<BTreeMap<String, String>> = OnceLock::new();
    let data = DATA.get_or_init(|| {
        serde_json::from_str(include_str!("casefold-v15.json")).expect("frozen Unicode15 table")
    });
    s.chars()
        .map(|c| {
            data.get(&c.to_string())
                .cloned()
                .unwrap_or_else(|| c.to_string())
        })
        .collect()
}
