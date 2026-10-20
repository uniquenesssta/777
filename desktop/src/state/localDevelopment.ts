import { request } from '../bridge';
// The launcher owns the local ledger, certificate and identity. Do not reuse a remote URL/pin.
export async function selectCurrentLocalDevelopment() {
  const state = await request<{root:string;backup_dir:string}>('developer', {request:{op:'status'}});
  return request<{connection:{certificate_sha256:string}}>('developer', {request:{
    op:'select',root:state.root,backup_dir:state.backup_dir,initialize:false,username:null,password:null,
  }});
}
