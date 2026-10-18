use quote_host::{cluster::{config::{self,Config,Role},membership,snapshot::{self,FileEntry,Manifest}},files};
use quote_ledger::store;
use serde_json::json;
use std::{collections::BTreeMap,fs,path::PathBuf};
struct Fixture {root:PathBuf, config:Config}
impl Fixture {
    fn new()->Self {
        let root=std::env::temp_dir().join(format!("777-cluster-test-{}",store::uid().unwrap()));
        fs::create_dir_all(root.join("private/cluster/generations")).unwrap();
        let inventory=store::create(&root.join("private/ledger.sqlite3")).unwrap();
        quote_host::auth::Auth::create(&root.join("private/auth.sqlite3"),"manager","synthetic-cluster-password").unwrap();
        quote_host::outputs::Outputs::create(&root.join("private/outputs.sqlite3"),inventory["ledger_id"].as_str().unwrap()).unwrap();
        let cert=rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
        let config=Config{format:config::FORMAT.into(),cluster_id:store::uid().unwrap(),ledger_id:inventory["ledger_id"].as_str().unwrap().into(),node_id:store::uid().unwrap(),role:Role::Primary,primary:quote_security::Connection{url:"https://localhost:8477".into(),certificate_pem:cert.cert.pem(),certificate_sha256:store::hash(cert.cert.der())}};
        files::new_file(&config::directory(&root).join("config.json"),&serde_json::to_vec(&config).unwrap()).unwrap();
        membership::create(&root).unwrap();
        Self{root,config}
    }
    fn enroll(&self,invite:&serde_json::Value,node:&str,secret:&str)->quote_host::Result<serde_json::Value>{
        membership::enroll(&self.root,&json!({"cluster_id":self.config.cluster_id,"ledger_id":self.config.ledger_id,"grant_id":invite["grant_id"],"ticket":invite["ticket"],"node_id":node,"credential":secret}))
    }
}
impl Drop for Fixture {fn drop(&mut self){let _=fs::remove_dir_all(&self.root);}}
#[test]
fn tickets_bind_exactly_one_node_and_revocation_blocks_retry_and_forward_credentials(){
    let f=Fixture::new();let invite=membership::invite(&f.root).unwrap();
    let node=store::uid().unwrap();let secret=membership::credential().unwrap();
    let one=f.enroll(&invite,&node,&secret).unwrap();
    assert_eq!(one,f.enroll(&invite,&node,&secret).unwrap());
    assert_eq!(f.enroll(&invite,&store::uid().unwrap(),&secret).unwrap_err().code,"CLUSTER_INVITATION_ALREADY_USED");
    assert!(f.enroll(&invite,&node,&membership::credential().unwrap()).is_err());
    membership::authenticate(&f.root,&node,&secret).unwrap();
    assert!(membership::authenticate(&f.root,&node,&membership::credential().unwrap()).is_err());
    membership::revoke(&f.root,&node).unwrap();
    assert_eq!(membership::authenticate(&f.root,&node,&secret).unwrap_err().code,"CLUSTER_PEER_REVOKED");
    assert_eq!(f.enroll(&invite,&node,&secret).unwrap_err().code,"CLUSTER_PEER_REVOKED");
    let records=membership::listing(&f.root).unwrap().to_string();
    assert!(!records.contains(&secret));assert!(!records.contains(invite["ticket"].as_str().unwrap()));
}
#[test]
fn manifest_paths_identity_hashes_and_monotonic_publication_are_enforced(){
    let f=Fixture::new();let mut entries=BTreeMap::new();
    for name in ["ledger.sqlite3","auth.sqlite3","outputs.sqlite3"] {let path=f.root.join("private").join(name);entries.insert(name.into(),FileEntry{size:path.metadata().unwrap().len(),sha256:files::sha(&path).unwrap()});}
    let mut m=Manifest{format:snapshot::FORMAT.into(),cluster_id:f.config.cluster_id.clone(),ledger_id:f.config.ledger_id.clone(),generation:2,inventory:quote_ledger::integrity::inventory(&store::open(&f.root.join("private/ledger.sqlite3"),false).unwrap()).unwrap(),files:entries};
    snapshot::validate_manifest(&m,&f.config).unwrap();
    for bad in ["../service.json","output-blobs/../../tls-key.pem","tls-key.pem","output-blobs/not-a-uuid.xlsx","output-blobs/00000000-0000-0000-0000-000000000001.exe"] {assert!(!snapshot::valid_name(bad));}
    let stage=config::directory(&f.root).join(format!("stage-{}",store::uid().unwrap()));fs::create_dir(&stage).unwrap();
    fs::create_dir(stage.join("output-blobs")).unwrap();
    for name in m.files.keys(){files::copy(&f.root.join("private").join(name),&stage.join(name)).unwrap();}
    let publication=snapshot::publish(&f.root,&stage,&m).unwrap();
    assert_eq!(snapshot::read(&f.root,&publication).unwrap().generation,2);
    m.generation=1;assert_eq!(snapshot::publish(&f.root,&stage,&m).unwrap_err().code,"CLUSTER_SOURCE_ROLLBACK");
    m.generation=2;m.files.get_mut("auth.sqlite3").unwrap().size=2;
    assert_eq!(snapshot::publish(&f.root,&stage,&m).unwrap_err().code,"CLUSTER_GENERATION_CONFLICT");
    m.ledger_id=store::uid().unwrap();assert!(snapshot::validate_manifest(&m,&f.config).is_err());
    let path=snapshot::folder(&f.root,&publication).unwrap().join("manifest.json");fs::write(path,b"corrupted").unwrap();
    assert_eq!(snapshot::read(&f.root,&publication).unwrap_err().code,"CLUSTER_MANIFEST_HASH_INVALID");
}
