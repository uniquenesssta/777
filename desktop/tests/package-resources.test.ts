// File/path unit checks only: no Tauri build, installer or preparation suite.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {relativeResourcePath,resourceInventory,stageResources} from '../tools/package-resources.mjs';
import {payloadInventory} from '../tools/automatic-release.mjs';
import {bundleConfig} from '../tools/package.mjs';

test('Windows resource paths use the project drive even when originals are on another drive',()=>{
  const project=String.raw`O:\Project\liuliu\777\desktop\src-tauri`;
  const original=String.raw`C:\Users\uniqu\AppData\Local\Quote777Development\local-issuance\id.bin.stage\node-run.ps1`;
  assert.throws(()=>relativeResourcePath(original,project,path.win32),/PACKAGE_RESOURCE_DRIVE_CONFLICT/);
  for(const name of ['host/node-run.ps1','host/quote-host.exe','automatic/package.json','licenses/fonts/Noto-OFL.txt']){
    const staged=path.win32.join(project,'../../target/packages/manager/resources/id',name);
    const relative=relativeResourcePath(staged,project,path.win32);
    assert.equal(relative,`../../target/packages/manager/resources/id/${name}`);
    assert(!relative.includes(':'));assert(!relative.includes('\\'));
    assert.equal(path.win32.resolve(project,relative),staged);
  }
});

test('Tauri mapping, staged bytes and signed inventory agree for outside sources and recursive licenses',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'777-resource-map-'));
  try{
    const project=path.join(root,'repo/desktop/src-tauri'),external=path.join(root,'outside 资料'),stage=path.join(root,'repo/target/packages/resources/id');
    await fs.mkdir(project,{recursive:true});await fs.mkdir(external);
    await fs.mkdir(path.join(root,'repo/desktop/licenses'));
    await fs.writeFile(path.join(root,'repo/desktop/licenses/font.txt'),'real test notice');
    await fs.writeFile(path.join(external,'node-run.ps1'),'\ufeff# 中文后台');
    await fs.writeFile(path.join(external,'package.json'),'{}');
    const source={'../licenses/':'licenses/fonts/',[path.join(external,'node-run.ps1')]:'host/node-run.ps1',[path.join(external,'package.json')]:'automatic/package.json'};
    const mapping=await stageResources(source,project,stage);
    assert.equal(Object.keys(mapping).length,3);
    const all=await resourceInventory(mapping,project,{includeEnvelope:true});
    assert.equal(await fs.readFile(all['host/node-run.ps1'],'utf8'),'\ufeff# 中文后台');
    assert.equal(await fs.readFile(all['licenses/fonts/font.txt'],'utf8'),'real test notice');
    const before=await payloadInventory(await resourceInventory(mapping,project));
    assert.deepEqual(before,await payloadInventory(await resourceInventory(source,project)));
    await fs.writeFile(path.join(external,'package.json'),'signed scoped test envelope');
    await fs.copyFile(path.join(external,'package.json'),all['automatic/package.json']);
    assert.deepEqual(await payloadInventory(await resourceInventory(mapping,project)),before);
    assert.equal(await fs.readFile(all['automatic/package.json'],'utf8'),'signed scoped test envelope');
    await fs.writeFile(all['host/node-run.ps1'],'changed');
    assert.notDeepEqual(await payloadInventory(await resourceInventory(mapping,project)),before);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('default notices resolve from src-tauri, matching the native build script',async()=>{
  const project=fileURLToPath(new URL('../src-tauri/',import.meta.url));
  const mapping=bundleConfig('sales','0.1.0','hook').bundle.resources;
  const files=await resourceInventory(mapping,project);
  assert.equal(files['licenses/desktop-notices.md'],path.resolve(project,'../THIRD_PARTY_NOTICES.md'));
  assert(files['licenses/fonts/Noto-OFL.txt']);assert(files['licenses/fonts/Inter-OFL.txt']);
  for(const source of Object.values(files))assert((await fs.stat(source as string)).isFile());
});

test('missing resources and ambiguous or escaping destinations remain failures',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'777-resource-reject-'));
  try{
    await fs.writeFile(path.join(root,'a'),'a');await fs.writeFile(path.join(root,'b'),'b');
    await assert.rejects(resourceInventory({'absent':'host/missing'},root),{code:'ENOENT'});
    await assert.rejects(resourceInventory({'a':'host/same','b':'host/same'},root),/PACKAGE_RESOURCE_TARGET_CONFLICT/);
    await assert.rejects(stageResources({'a':'../escape'},root,path.join(root,'stage')),/PACKAGE_RESOURCE_TARGET_INVALID/);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});
