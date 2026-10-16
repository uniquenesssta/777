// Windows-only release orchestration using the pinned Tauri/NSIS toolchain.
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { digest, json, options, publicConnection, readJson, requireDelivery, verifyRelease } from './deployment.mjs';
const desktop = fileURLToPath(new URL('../', import.meta.url));
const root = path.dirname(desktop);
export function installerHooks(delivery) {
  requireDelivery(delivery);
  const other = delivery === 'manager' ? 'sales' : 'manager';
  return `!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$INSTDIR\\quote777-${other}.exe" 0 +3
    SetErrorLevel 5
    Abort "DELIVERY_INSTALL_DIRECTORY_CONFLICT"
  ReadINIStr $0 "$INSTDIR\\quote777-install.ini" "release" "delivery"
  StrCmp $0 "" quote777_delivery_check_done
  StrCmp $0 "${delivery}" quote777_delivery_check_done
    SetErrorLevel 5
    Abort "DELIVERY_INSTALL_DIRECTORY_CONFLICT"
  quote777_delivery_check_done:
!macroend
!macro NSIS_HOOK_POSTINSTALL
  WriteINIStr "$INSTDIR\\quote777-install.ini" "release" "delivery" "${delivery}"
!macroend
!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$INSTDIR\\quote777-install.ini"
  RMDir "$INSTDIR"
!macroend
`;
}
export function bundleConfig(delivery, version, hooks, runtime = 'offlineInstaller') {
  const id = requireDelivery(delivery);
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw Error('RELEASE_VERSION_INVALID');
  if (!['offlineInstaller', 'downloadBootstrapper'].includes(runtime)) throw Error('WEBVIEW_MODE_INVALID');
  return {
    productName: id.productName, identifier: id.identifier, mainBinaryName: id.binary, version,
    app: { windows: [{ label: 'main', title: id.productName, width: 1440, height: 884, minWidth: 640, minHeight: 480 }] },
    bundle: {
      active: true, targets: ['nsis'], useLocalToolsDir: true, category: 'Business', shortDescription: id.productName,
      resources: { '../THIRD_PARTY_NOTICES.md': 'licenses/desktop-notices.md', '../resources/licenses/': 'licenses/fonts/' },
      windows: { allowDowngrades: false, webviewInstallMode: { type: runtime, silent: true },
        nsis: { installMode: 'currentUser', languages: ['SimpChinese'], displayLanguageSelector: false,
          startMenuFolder: '记账器', installerHooks: hooks } },
    },
  };
}
const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
export async function verifyProductionFrontend(directory) {
  const scripts = (await fs.readdir(path.join(directory, 'assets'))).filter(name => name.endsWith('.js'));
  if (!scripts.length) throw Error('PRODUCTION_FRONTEND_MISSING');
  for (const name of scripts) {
    const source = await fs.readFile(path.join(directory, 'assets', name), 'utf8');
    if (source.includes('current-password') || source.includes('服务证书（PEM）')) throw Error('DEVELOPMENT_FORM_IN_RELEASE');
  }
}
async function run(args, env) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { cwd: desktop, stdio: 'inherit', env });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(Error('TAURI_BUILD_FAILED: ' + code)));
  });
}
export async function build(args) {
  const a = options(args, ['--delivery', '--connection', '--output', '--version', '--webview']);
  const delivery = a['--delivery'], identity = requireDelivery(delivery);
  if (!a['--connection'] || !a['--output']) throw Error('package --delivery manager|sales --connection connection.json --output empty-directory');
  const config = publicConnection(await readJson(a['--connection']));
  if (process.platform !== 'win32') throw Error('WINDOWS_PACKAGING_REQUIRED');
  if (git(['status', '--porcelain'])) throw Error('CLEAN_SOURCE_REQUIRED');
  const source = git(['rev-parse', 'HEAD']);
  const base = await readJson(path.join(desktop, 'src-tauri/tauri.conf.json'));
  const version = a['--version'] ?? base.version;
  const output = path.resolve(a['--output']);
  // Exclusive creation makes stale installers impossible to mistake for this build.
  await fs.mkdir(output, { recursive: false });
  await fs.mkdir(path.join(root, 'target'), { recursive: true });
  const temporary = await fs.mkdtemp(path.join(root, 'target', 'package-input-'));
  try {
    const hooks = path.join(temporary, 'installer-hooks.nsh');
    const overlay = bundleConfig(delivery, version, hooks, a['--webview']);
    const publicText = json(config);
    const meta = {
      schema: '777-desktop-package-v1', delivery, identifier: identity.identifier, version,
      source_commit: source, connection_sha256: digest(Buffer.from(publicText)),
      profile_compatibility_epoch: 1, service_protocol: '777-service-v1', device_protocol: '777-device-auth-v1',
    };
    await fs.writeFile(hooks, installerHooks(delivery));
    await fs.writeFile(path.join(temporary, 'tauri.json'), json(overlay));
    await fs.writeFile(path.join(temporary, 'connection.json'), publicText);
    await fs.writeFile(path.join(temporary, 'metadata.json'), json(meta));
    const target = path.join(root, 'target', 'packages', delivery);
    const env = { ...process.env, CARGO_TARGET_DIR: target, CARGO_BUILD_JOBS: process.env.CARGO_BUILD_JOBS ?? '1',
      QUOTE777_PACKAGE_DELIVERY: delivery, VITE_QUOTE777_DELIVERY: delivery, QUOTE777_PACKAGE_CONNECTION: path.join(temporary, 'connection.json'),
      QUOTE777_PACKAGE_METADATA: path.join(temporary, 'metadata.json') };
    delete env.TAURI_CONFIG;
    await run([path.join(desktop, 'node_modules/@tauri-apps/cli/tauri.js'), 'build', '--ci', '--features', delivery,
      '--bundles', 'nsis', '--config', path.join(temporary, 'tauri.json'), '--', '--locked'], env);
    await verifyProductionFrontend(path.join(desktop, 'dist'));
    if (git(['status', '--porcelain'])) throw Error('BUILD_MODIFIED_SOURCE: inspect worktree before publishing');
    const binary = path.join(target, 'release', identity.binary + '.exe');
    const info = JSON.parse(execFileSync(binary, ['--package-info'], { encoding: 'utf8', timeout: 30000 }));
    for (const key of Object.keys(meta)) if (info[key] !== meta[key]) throw Error('COMPILED_PACKAGE_MISMATCH: ' + key);
    if (info.verification !== false || info.release !== true || info.custom_protocol !== true) throw Error('PRODUCTION_BINARY_REQUIRED');
    const installerDir = path.join(target, 'release/bundle/nsis');
    const installers = (await fs.readdir(installerDir)).filter(n => n.startsWith(identity.productName + '_' + version + '_') && n.endsWith('-setup.exe'));
    if (installers.length !== 1) throw Error('INSTALLER_NOT_UNIQUE');
    const installer = installers[0];
    await fs.copyFile(binary, path.join(output, identity.binary + '.exe'));
    await fs.copyFile(path.join(installerDir, installer), path.join(output, installer));
    await fs.writeFile(path.join(output, 'connection.json'), publicText);
    await fs.copyFile(path.join(desktop, 'THIRD_PARTY_NOTICES.md'), path.join(output, 'THIRD_PARTY_NOTICES.md'));
    await fs.copyFile(path.join(desktop, 'tools/enroll.ps1'), path.join(output, 'enroll.ps1'));
    const files = [];
    for (const name of await fs.readdir(output)) {
      const bytes = await fs.readFile(path.join(output, name));
      files.push({ name, bytes: bytes.length, sha256: digest(bytes) });
    }
    const manifest = { ...meta, schema: '777-desktop-release-v1', product_name: identity.productName,
      release: true, verification: false, custom_protocol: true, installer, files,
      webview_mode: overlay.bundle.windows.webviewInstallMode.type,
      profile: `%LOCALAPPDATA%\\cn.uniqueness.quote777\\${delivery}`,
      frontend_storage: `%LOCALAPPDATA%\\cn.uniqueness.quote777\\${delivery}\\webview2`,
      pinned_inputs: { cargo_lock: digest(await fs.readFile(path.join(root, 'Cargo.lock'))),
        npm_lock: digest(await fs.readFile(path.join(desktop, 'package-lock.json'))),
        fonts: await readJson(path.join(desktop, 'resources/fonts.json')) },
      installer_config: overlay,
    };
    await fs.writeFile(path.join(output, 'release.json'), json(manifest));
    await verifyRelease(output);
    console.log(json({ delivery, version, output, installer, source_commit: source }));
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  build(process.argv.slice(2)).catch(error => { console.error(error.code ?? error.message); process.exitCode = 1; });
}
