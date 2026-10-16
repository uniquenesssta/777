import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { bundleConfig } from "../tools/package.mjs";

const desktop = fileURLToPath(new URL("../", import.meta.url));
const cli = path.join(desktop, "node_modules/@tauri-apps/cli/tauri.js");
const tracked = fs.readFileSync(
  path.join(desktop, "src-tauri/Cargo.toml"),
  "utf8",
);

function probe(manifest: string, action: "build" | "dev", overlay?: Record<string, unknown>) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "777-manifest-check-"));
  try {
    const app = path.join(folder, "src-tauri");
    fs.mkdirSync(path.join(app, "src"), { recursive: true });
    fs.writeFileSync(path.join(app, "src/main.rs"), "fn main() {}\n");
    const source = manifest
      .replace("edition.workspace = true", 'edition = "2021"')
      .replace("rust-version.workspace = true", 'rust-version = "1.97.1"')
      .replace("license.workspace = true", 'license = "Apache-2.0"');
    const target = path.join(app, "Cargo.toml");
    fs.writeFileSync(target, source);
    const config = JSON.parse(
      fs.readFileSync(path.join(desktop, "src-tauri/tauri.conf.json"), "utf8"),
    );
    config.build.beforeDevCommand = "";
    config.build.beforeBuildCommand = "";
    config.build.frontendDist = path.join(folder, "dist");
    fs.mkdirSync(config.build.frontendDist);
    fs.writeFileSync(path.join(app, "tauri.conf.json"), JSON.stringify(config));
    if (overlay) fs.writeFileSync(path.join(app, "package.json"), JSON.stringify(overlay));
    // The intentionally absent workspace stops Cargo metadata after Tauri's
    // manifest pass: no compilation, dependency download, host or GUI startup.
    const result = spawnSync(
      process.execPath,
      [cli, action, ...(action === "build" ? ["--no-bundle"] : []), ...(overlay ? ["--config", path.join(app, "package.json")] : [])],
      {
        cwd: folder,
        encoding: "utf8",
        timeout: 20000,
      },
    );
    assert.ifError(result.error);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /cargo metadata/);
    return { before: source, after: fs.readFileSync(target, "utf8") };
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
}

test("actual pinned Tauri CLI reproduces the previous manifest rewrite", () => {
  const old = tracked.replace(
    'tauri-build = { version = "=2.7.2", features = [] }',
    'tauri-build = { version = "=2.7.2" }',
  );
  for (const action of ["build", "dev"] as const) {
    const result = probe(old.replace(/\r\n/g, "\n"), action);
    assert.equal(
      result.after,
      result.before.replace(
        'tauri-build = { version = "=2.7.2" }',
        'tauri-build = { version = "=2.7.2", features = [] }',
      ),
    );
    assert.notEqual(result.after, result.before);
  }
});

test("tracked manifest stays unchanged through actual Tauri dev/build for LF and CRLF", () => {
  for (const eol of ["\n", "\r\n"]) {
    const source = tracked.replace(/\r\n/g, "\n").replace(/\n/g, eol);
    for (const action of ["dev", "build"] as const) {
      const result = probe(source, action);
      assert.equal(result.after, result.before);
    }
  }
});

test("actual Tauri role and upgrade overlays preserve the source Cargo manifest", () => {
  for (const kind of ["manager", "sales"]) {
    const result = probe(tracked, "build", { identifier: `cn.uniqueness.quote777.${kind}`, mainBinaryName: `quote777-${kind}`, version: "0.1.1" });
    assert.equal(result.after, result.before);
  }
});

test("pinned Tauri parser accepts both complete Windows NSIS overlays", () => {
  for (const kind of ["manager", "sales"]) {
    const result = probe(tracked, "build", bundleConfig(kind, "0.1.0", "installer-hooks.nsh"));
    assert.equal(result.after, result.before);
  }
});
