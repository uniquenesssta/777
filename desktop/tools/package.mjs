// Windows-only release orchestration using the pinned Tauri/NSIS toolchain.
import fs from 'node:fs/promises';
import { packagePermissions } from './package-permissions.mjs';
import { issuerConnection, payloadInventory, resourceInventory, issuePackage, managerResources } from './automatic-release.mjs';
import { randomUUID } from 'node:crypto';
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
  ${delivery === 'manager' ? 'nsExec::ExecToStack \'"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\host\\install.ps1" -Resources "$INSTDIR"\'\n  Pop $0\n  Pop $1' : ''}
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
    if (source.includes('current-password') || source.includes('服务证书（PEM）') || source.includes('开发部署') || source.includes('DEVELOPER_LAUNCHER_REQUIRED')) throw Error('DEVELOPMENT_FORM_IN_RELEASE');
  }
}
async function run(args, env) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { cwd: desktop, stdio: 'inherit', env });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(Error('TAURI_BUILD_FAILED: ' + code)));
  });
}
// Only the newly created, empty output directory is excluded; tracked source stays checked.
export async function ignoreGeneratedOutput(output, repository = root) {
  const relative = path.relative(await fs.realpath(repository), await fs.realpath(output));
  if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) return;
  if ((await fs.readdir(output)).length) throw Error('PACKAGE_OUTPUT_NOT_EMPTY');
  const gitPath = execFileSync('git', ['rev-parse', '--git-path', 'info/exclude'], { cwd: repository, encoding: 'utf8' }).trim();
  const pattern = '/' + relative.split(path.sep).join('/').replace(/[\\*?\[\]]/g, character => '\\' + character) + '/';
  await fs.appendFile(path.resolve(repository, gitPath), '\n' + pattern + '\n');
}

export async function build(args) {
  const a = options(args, ['--delivery', '--issuer-state', '--candidate', '--package-id', '--output', '--version', '--webview', '--permissions']);
  const delivery = a['--delivery'], identity = requireDelivery(delivery);
  if (!a['--issuer-state'] || !a['--candidate'] || !a['--output']) throw Error('ISSUER_NOT_READY');
  const issuerState=path.resolve(a['--issuer-state']),candidate=path.resolve(a['--candidate']);
  const packageId=a['--package-id']??randomUUID();
  const hostExecutable=path.join(root,'target/release/quote-host.exe');
  const permissions = packagePermissions(delivery, a['--permissions'] === undefined ? undefined : JSON.parse(a['--permissions']));
  const config = issuerConnection(hostExecutable,issuerState);
  if (process.platform !== 'win32') throw Error('WINDOWS_PACKAGING_REQUIRED');
  if (git(['status', '--porcelain'])) throw Error('CLEAN_SOURCE_REQUIRED');
  const source = git(['rev-parse', 'HEAD']);
  const base = await readJson(path.join(desktop, 'src-tauri/tauri.conf.json'));
  const version = a['--version'] ?? base.version;
  const output = path.resolve(a['--output']);
  const temporary=candidate+'.stage';
  const controlFile=path.join(temporary,'build-state.json');
  let cached=await readJson(controlFile).catch(e=>{if(e.code!=='ENOENT')throw e;return null;});
  if (cached) {
    if(cached.package_id!==packageId||cached.output!==output||cached.source!==source||cached.delivery!==delivery||JSON.stringify(cached.permissions)!==JSON.stringify(permissions)||cached.version!==version||cached.runtime!==(a['--webview']??'offlineInstaller')) throw Error('PACKAGE_RESUME_CONFLICT');
  } else {
    await fs.mkdir(output,{recursive:false}).catch(async e=>{if(e.code!=='EEXIST'||(await fs.readdir(output)).length)throw e;});await ignoreGeneratedOutput(output);
    await fs.mkdir(temporary,{recursive:false});
    cached={package_id:packageId,output,source,delivery,permissions,version,runtime:a['--webview']??'offlineInstaller',built:false};
    await fs.writeFile(controlFile,json(cached));
  }
  try {
    const hooks = path.join(temporary, 'installer-hooks.nsh');
    const overlay = bundleConfig(delivery, version, hooks, a['--webview']);
    const publicText = json(config);
    const meta = {
      schema: '777-desktop-package-v1', delivery, permissions, identifier: identity.identifier, version,
      source_commit: source, connection_sha256: digest(Buffer.from(publicText)),
      package_id: packageId, profile_compatibility_epoch: 1, service_protocol: '777-service-v1', device_protocol: '777-auto-enrollment-v1',
    };
    await fs.writeFile(hooks, installerHooks(delivery));
    if (delivery==='manager') Object.assign(overlay.bundle.resources,await managerResources(root,temporary));
    // A placeholder is never distributable. Registration is added only after the immutable binary is built.
    if(!cached.built) await fs.writeFile(path.join(temporary,'package.json'),'{}');
    overlay.bundle.resources[path.join(temporary,'package.json')]='automatic/package.json';
    await fs.writeFile(path.join(temporary, 'tauri.json'), json(overlay));
    await fs.writeFile(path.join(temporary, 'connection.json'), publicText);
    await fs.writeFile(path.join(temporary, 'metadata.json'), json(meta));
    const target = path.join(root, 'target', 'packages', delivery);
    const env = { ...process.env, CARGO_TARGET_DIR: target, CARGO_BUILD_JOBS: process.env.CARGO_BUILD_JOBS ?? '1',
      QUOTE777_PACKAGE_DELIVERY: delivery, VITE_QUOTE777_DELIVERY: delivery, QUOTE777_PACKAGE_CONNECTION: path.join(temporary, 'connection.json'),
      QUOTE777_PACKAGE_METADATA: path.join(temporary, 'metadata.json') };
    delete env.TAURI_CONFIG;
    const binary = path.join(target, 'release', identity.binary + '.exe');
    if(!cached.built) {
      await run([path.join(desktop, 'node_modules/@tauri-apps/cli/tauri.js'), 'build', '--ci', '--features', delivery,
      '--no-bundle', '--no-binary-patching', '--config', path.join(temporary, 'tauri.json'), '--', '--locked'], env);
      await verifyProductionFrontend(path.join(desktop, 'dist'));
      await fs.copyFile(binary,path.join(temporary,'built-program.exe'));
      cached.built=true;await fs.writeFile(controlFile,json(cached));
    } else {
      await fs.copyFile(path.join(temporary,'built-program.exe'),binary);
    }
    if (git(['status', '--porcelain'])) throw Error('BUILD_MODIFIED_SOURCE: inspect worktree before publishing');
    const payloadFiles = {[identity.binary+'.exe']:binary,...await resourceInventory(overlay.bundle.resources,desktop)};
    const payload=await payloadInventory(payloadFiles);
    await issuePackage({executable:hostExecutable,state:issuerState,candidate,temporary,packageId,delivery,permissions,version,payload});
    await run([path.join(desktop,'node_modules/@tauri-apps/cli/tauri.js'),'bundle','--ci','--features',delivery,'--bundles','nsis','--no-binary-patching','--config',path.join(temporary,'tauri.json')],env);
    if (JSON.stringify(await payloadInventory(payloadFiles))!==JSON.stringify(payload)) throw Error('ISSUED_PAYLOAD_CHANGED');
    const info = JSON.parse(execFileSync(binary, ['--package-info'], { encoding: 'utf8', timeout: 30000 }));
    for (const key of Object.keys(meta)) if (JSON.stringify(info[key]) !== JSON.stringify(meta[key])) throw Error('COMPILED_PACKAGE_MISMATCH: ' + key);
    if (info.verification !== false || info.release !== true || info.custom_protocol !== true) throw Error('PRODUCTION_BINARY_REQUIRED');
    const installerDir = path.join(target, 'release/bundle/nsis');
    const installers = (await fs.readdir(installerDir)).filter(n => n.startsWith(identity.productName + '_' + version + '_') && n.endsWith('-setup.exe'));
    if (installers.length !== 1) throw Error('INSTALLER_NOT_UNIQUE');
    const installer = installers[0];
    await fs.copyFile(binary, path.join(output, identity.binary + '.exe'));
    await fs.copyFile(path.join(installerDir, installer), path.join(output, installer));
    await fs.writeFile(path.join(output, 'connection.json'), publicText);
    await fs.copyFile(path.join(desktop, 'THIRD_PARTY_NOTICES.md'), path.join(output, 'THIRD_PARTY_NOTICES.md'));
    await fs.mkdir(path.join(output,'automatic'),{recursive:true});
    await fs.copyFile(path.join(temporary,'package.json'),path.join(output,'automatic/package.json'));
    await fs.writeFile(path.join(output,'payload.json'),json(payload));
    await fs.copyFile(path.join(desktop, 'tools/install.ps1'), path.join(output, 'install.ps1'));
    await fs.writeFile(path.join(output, 'install.cmd'), '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0install.ps1"\r\n');
    const files = [];
    for (const name of ['automatic/package.json',...(await fs.readdir(output)).filter(n=>!['automatic','release.json'].includes(n))]) {
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
    await fs.rm(temporary,{recursive:true,force:true}).catch(()=>{});
    console.log(json({ delivery, version, output, installer, source_commit: source }));
  } catch(error) {
    // Leave protected issuance candidates for recovery if offline. Never publish partial release.json.
    await fs.rm(path.join(output,'release.json'),{force:true});
    throw error;
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.env.QUOTE777_PACKAGE_CONTROL_STDIN === '1') {
    const { createInterface } = await import('node:readline');
    const lines = createInterface({ input: process.stdin });
    let authorized = false;
    for await (const line of lines) { authorized = line === 'start'; break; }
    if (!authorized) throw Error('PACKAGE_OWNER_REQUIRED');
  }
  build(process.argv.slice(2)).catch(error => { console.error(error.code ?? error.message); process.exitCode = 1; });
}
