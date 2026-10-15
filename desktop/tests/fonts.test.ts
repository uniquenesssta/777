import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { prepareFonts } from "../tools/prepare-fonts.mjs";

test("pinned font download is atomic, cached and usable without network", async () => {
  const messages:string[]=[];
  const log=(message:string)=>{messages.push(message);};
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),"777-font-"));
  const bytes=Buffer.from("isolated download bytes");
  const asset={file:"test.woff2",url:"https://invalid.example/test",bytes:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex")};
  try {
    await prepareFonts({directory,log,assets:[asset],fetcher:async()=>new Response(bytes)});
    assert.deepEqual(await fs.readFile(path.join(directory,asset.file)),bytes);
    await prepareFonts({directory,log,assets:[asset],fetcher:async()=>{throw Error("network must not be reached");}});
    assert.deepEqual(await fs.readdir(directory),[asset.file]);
    assert.deepEqual(messages,["准备离线字体：test.woff2"]);
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});

test("wrong download and corrupted cache never become accepted font assets", async () => {
  const messages:string[]=[];
  const log=(message:string)=>{messages.push(message);};
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),"777-font-"));
  const asset={file:"test.woff2",url:"https://invalid.example/test",bytes:5,sha256:"0".repeat(64)};
  try {
    await assert.rejects(prepareFonts({directory,log,assets:[asset],fetcher:async()=>new Response("wrong")}),/FONT_DOWNLOAD_HASH_MISMATCH/);
    assert.deepEqual(await fs.readdir(directory),[]);
    await fs.writeFile(path.join(directory,asset.file),"wrong");
    await assert.rejects(prepareFonts({directory,log,assets:[asset],fetcher:async()=>{throw Error("must preserve corrupt evidence");}}),/FONT_CACHE_HASH_MISMATCH/);
    assert.equal(await fs.readFile(path.join(directory,asset.file),"utf8"),"wrong");
    assert.deepEqual(messages,["准备离线字体：test.woff2"]);
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});

// Ordinary CLI output is collected from a separate child, never forwarded into
// node:test's serialized event stream (Node 22 issue nodejs/node#65934).
test("ordinary font preparation keeps its Chinese CLI progress", async () => {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),"777-font-cli-"));
  const bytes=Buffer.from("CLI fixture");
  const asset={file:"cli.woff2",url:"https://invalid.example/cli",bytes:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex")};
  const source=`import {prepareFonts} from ${JSON.stringify(new URL("../tools/prepare-fonts.mjs",import.meta.url).href)};
    await prepareFonts({directory:${JSON.stringify(directory)},assets:${JSON.stringify([asset])},fetcher:async()=>new Response("CLI fixture")});`;
  const env={...process.env};delete env.NODE_TEST_CONTEXT;
  try {
    const child=spawnSync(process.execPath,["--input-type=module","-e",source],{encoding:"utf8",timeout:10000,env});
    assert.ifError(child.error);assert.equal(child.status,0,child.stderr);
    assert.equal(child.stdout.trimEnd(),"准备离线字体：cli.woff2");
    assert.deepEqual(await fs.readFile(path.join(directory,asset.file)),bytes);
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});
