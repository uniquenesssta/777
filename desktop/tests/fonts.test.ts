import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { prepareFonts } from "../tools/prepare-fonts.mjs";

test("pinned font download is atomic, cached and usable without network", async () => {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),"777-font-"));
  const bytes=Buffer.from("isolated download bytes");
  const asset={file:"test.woff2",url:"https://invalid.example/test",bytes:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex")};
  try {
    await prepareFonts({directory,assets:[asset],fetcher:async()=>new Response(bytes)});
    assert.deepEqual(await fs.readFile(path.join(directory,asset.file)),bytes);
    await prepareFonts({directory,assets:[asset],fetcher:async()=>{throw Error("network must not be reached");}});
    assert.deepEqual(await fs.readdir(directory),[asset.file]);
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});

test("wrong download and corrupted cache never become accepted font assets", async () => {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),"777-font-"));
  const asset={file:"test.woff2",url:"https://invalid.example/test",bytes:5,sha256:"0".repeat(64)};
  try {
    await assert.rejects(prepareFonts({directory,assets:[asset],fetcher:async()=>new Response("wrong")}),/FONT_DOWNLOAD_HASH_MISMATCH/);
    assert.deepEqual(await fs.readdir(directory),[]);
    await fs.writeFile(path.join(directory,asset.file),"wrong");
    await assert.rejects(prepareFonts({directory,assets:[asset],fetcher:async()=>{throw Error("must preserve corrupt evidence");}}),/FONT_CACHE_HASH_MISMATCH/);
    assert.equal(await fs.readFile(path.join(directory,asset.file),"utf8"),"wrong");
  } finally {await fs.rm(directory,{recursive:true,force:true});}
});
