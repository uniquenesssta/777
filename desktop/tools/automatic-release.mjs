// Offline developer signatures. Secrets remain in native DPAPI journals or final scoped envelopes.
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { digest, json, publicConnection, readJson } from './deployment.mjs';
export function native(executable, args) {
  try { return JSON.parse(execFileSync(executable, args, {encoding:'utf8',timeout:180000,windowsHide:true,stdio:['ignore','pipe','pipe']})); }
  catch (e) {
    let code='AUTOMATIC_ISSUANCE_FAILED';
    try { const response=JSON.parse(String(e.stderr));if (/^[A-Z][A-Z0-9_]{4,100}$/.test(response.error)) code=response.error; } catch {}
    throw Error(code);
  }
}
export function issuerConnection(executable,state) {
  const s=native(executable,['automatic-local-status','--state',state]);
  if (!s.ready) throw Error('LOCAL_SIGNER_UNAVAILABLE');
  if (s.profile?.primary_url!=='https://192.168.4.23:8479') throw Error('AUTOMATIC_SITE_CONFLICT');
  return publicConnection({schema:'777-public-connection-v1',connection:{url:s.profile.primary_url,...s.profile.tls}});
}
export async function payloadInventory(files) {
  const entries=[];
  for (const [name,file] of Object.entries(files).sort(([a],[b])=>a<b?-1:a>b?1:0)) {
    const bytes=await fs.readFile(file);entries.push({name,bytes:bytes.length,sha256:digest(bytes)});
  }
  return {format:'777-immutable-payload-v1',files:entries};
}
export async function resourceInventory(resources,base) {
  const files={};
  async function add(source,destination) {
    const stat=await fs.lstat(source);
    if(stat.isSymbolicLink())throw Error('PACKAGE_RESOURCE_LINK_FORBIDDEN');
    if(stat.isDirectory()){
      for(const name of await fs.readdir(source))await add(path.join(source,name),destination.replace(/\/$/,'')+'/'+name);
    }else if(stat.isFile())files[destination]=source;
    else throw Error('PACKAGE_RESOURCE_INVALID');
  }
  for(const [source,destination]of Object.entries(resources))if(destination!=='automatic/package.json')await add(path.resolve(base,source),destination);
  return files;
}
export async function issuePackage({executable,state,candidate,temporary,packageId,delivery,permissions,version,payload}) {
  const input=path.join(temporary,'issue.json'),output=path.join(temporary,'package.json');
  await fs.writeFile(input,json({package_id:packageId,delivery,permissions:[...permissions].sort(),version,artifact_sha256:digest(Buffer.from(json(payload)))}));
  native(executable,['automatic-local-issue','--state',state,'--input',input,'--candidate',candidate,'--output',output]);
  const p=await readJson(output,131072);
  if (p.format!=='777-local-package-v1'||p.manifest.package_id!==packageId||p.manifest.delivery!==delivery||p.manifest.artifact_sha256!==digest(Buffer.from(json(payload)))) throw Error('PACKAGE_ISSUANCE_CONFLICT');
  return output;
}
export function closeCandidate(executable,state,candidate) {
  return native(executable,['automatic-close','--state',state,'--candidate',candidate]);
}
export async function managerResources(root,temporary) {
  const resources={};
  const deployment=path.join(root,'deployment/windows');
  for (const name of ['install.ps1','install-paths.ps1','install-owner.ps1','install-discovery.ps1','node-run.ps1']) resources[path.join(deployment,'automatic',name)]=`host/${name}`;
  resources[path.join(deployment,'host-identity.ps1')]='host/host-identity.ps1';
  resources[path.join(deployment,'portable/host-log.ps1')]='host/host-log.ps1';
  resources[path.join(deployment,'portable/host-elevation.ps1')]='host/host-elevation.ps1';
  for(const name of ['quote-host','quote-ledger']) resources[path.join(root,'target/release',name+'.exe')]=`host/${name}.exe`;
  // PS 5.1 must see UTF-8 BOM for Chinese text. Build-owned copies only.
  for(const [source,destination] of Object.entries({...resources})) if(source.endsWith('.ps1')) {
    const out=path.join(temporary,path.basename(source));await fs.writeFile(out,'\ufeff'+(await fs.readFile(source,'utf8')).replace(/^\ufeff/,''));delete resources[source];resources[out]=destination;
  }
  return resources;
}
