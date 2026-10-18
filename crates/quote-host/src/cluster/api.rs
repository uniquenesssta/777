use super::{config, membership, snapshot::{self,Publication}};
use crate::{auth::Auth, fail, protocol::{fields,text}, service::Service, Error, Result};
use serde_json::{json,Value};
pub fn handle(s:&mut Service,method:&str,path:&str,token:&str,data:&Value,peer:&str)->Result<Value> {
    let config=config::ensure_primary(&s.root)?;
    if method!="POST" { return fail(405,"METHOD_NOT_ALLOWED"); }
    if path=="/v1/cluster/invite" || path=="/v1/cluster/peers" || path=="/v1/cluster/revoke" {
        Auth::admin(&s.auth.authenticate(token)?)?;
        return match path {
            "/v1/cluster/invite"=>{fields(data,&[],&[])?;membership::invite(&s.root)},
            "/v1/cluster/peers"=>{fields(data,&[],&[])?;Ok(json!({"cluster_id":config.cluster_id,"ledger_id":config.ledger_id,"current":snapshot::current(&s.root)?,"peers":membership::listing(&s.root)?}))},
            _=>{fields(data,&["node_id"],&[])?;membership::revoke(&s.root,text(&data["node_id"],36,true)?)},
        };
    }
    if path=="/v1/cluster/enroll" { return membership::enroll(&s.root,data); }
    let node=text(&data["node_id"],36,true)?;
    membership::authenticate(&s.root,node,token)?;
    if data["cluster_id"]!=config.cluster_id || data["ledger_id"]!=config.ledger_id { return fail(409,"CLUSTER_IDENTITY_CONFLICT"); }
    let base=["node_id","cluster_id","ledger_id"];
    match path {
        "/v1/cluster/manifest"=>{
            fields(data,&base,&[])?;
            let p=snapshot::current(&s.root)?.ok_or_else(||Error::new(503,"CLUSTER_INITIAL_SNAPSHOT_PENDING"))?;
            membership::lease(&s.root,node,p.generation,&p.sha256)?;
            Ok(json!({"publication":p,"manifest":snapshot::read(&s.root,&p)?}))
        },
        "/v1/cluster/chunk" | "/v1/cluster/ack"=>{
            fields(data,&base,if path.ends_with("chunk"){&["generation","manifest","name","offset"]}else{&["generation","manifest"]})?;
            let p=Publication{generation:data["generation"].as_u64().ok_or_else(||Error::new(422,"CLUSTER_GENERATION_INVALID"))?,sha256:text(&data["manifest"],64,true)?.into()};
            if path.ends_with("chunk") {
                let result=snapshot::chunk(&s.root,&p,text(&data["name"],128,true)?,data["offset"].as_u64().ok_or_else(||Error::new(422,"CLUSTER_CHUNK_OFFSET_INVALID"))?)?;
                membership::lease(&s.root,node,p.generation,&p.sha256)?;
                return Ok(result);
            }
            let _=snapshot::read(&s.root,&p)?;
            membership::acknowledge(&s.root,node,p.generation,&p.sha256)?;
            Ok(json!({"acknowledged":true,"generation":p.generation}))
        },
        "/v1/cluster/forward"=>{
            fields(data,&base,&["method","path","query","authorization","body"])?;
            let method=text(&data["method"],4,true)?;
            let path=text(&data["path"],4096,true)?;
            let query=text(&data["query"],4096,false)?;
            let authorization=text(&data["authorization"],256,false)?;
            if !["GET","POST"].contains(&method) || !path.starts_with("/v1/") || path.starts_with("/v1/cluster/") || path.contains(['?','#']) || serde_json::to_vec(&data["body"])?.len()>crate::protocol::BODY_LIMIT {
                return fail(422,"CLUSTER_FORWARD_INVALID");
            }
            // Stable original requests and actors are handled only by the one primary.
            s.handle(method,path,authorization,&data["body"],query,&format!("cluster:{node}:{peer}"))
        },
        _=>fail(404,"NOT_FOUND"),
    }
}
