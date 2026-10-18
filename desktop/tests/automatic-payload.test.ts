import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {payloadInventory,resourceInventory} from '../tools/automatic-release.mjs';
import {installerHooks,bundleConfig} from '../tools/package.mjs';
test('payload identity is stable across input order and changes when one resource changes',async()=>{
 const d=await fs.mkdtemp(path.join(os.tmpdir(),'777-payload-'));
 try{
  await fs.writeFile(path.join(d,'a'),'program');await fs.writeFile(path.join(d,'b'),'runner');
  const first=await payloadInventory({'z.exe':path.join(d,'a'),'host/run.ps1':path.join(d,'b')});
  assert.deepEqual(first,await payloadInventory({'host/run.ps1':path.join(d,'b'),'z.exe':path.join(d,'a')}));
  await fs.writeFile(path.join(d,'b'),'different runner');assert.notDeepEqual(first,await payloadInventory({'z.exe':path.join(d,'a'),'host/run.ps1':path.join(d,'b')}));
 }finally{await fs.rm(d,{recursive:true,force:true});}
});
test('recursive resources enter the payload while the enrollment envelope stays outside its own digest',async()=>{
 const d=await fs.mkdtemp(path.join(os.tmpdir(),'777-resource-'));
 try{await fs.mkdir(path.join(d,'licenses'));await fs.writeFile(path.join(d,'licenses/font.txt'),'notice');await fs.writeFile(path.join(d,'package.json'),'secret envelope');
 const files=await resourceInventory({'licenses/':'licenses/fonts/','package.json':'automatic/package.json'},d);
 assert.deepEqual(Object.keys(files),['licenses/fonts/font.txt']);
 }finally{await fs.rm(d,{recursive:true,force:true});}
});
test('mother alone invokes background installation and neither uninstall hook deletes business data',()=>{
 const mother=installerHooks('manager'),child=installerHooks('sales');
 assert(mother.includes('host\\install.ps1'));assert(!child.includes('install.ps1'));assert(!mother.includes('Quote777Service'));assert(!mother.includes('Unregister-ScheduledTask'));
 const config=bundleConfig('sales','0.1.0','hook');assert(!Object.values(config.bundle.resources).some((p:string)=>p.startsWith('host/')));
});
