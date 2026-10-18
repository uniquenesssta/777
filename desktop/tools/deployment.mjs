// Operator-side public configuration and one-device enrollment. Never copy a profile.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, X509Certificate } from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const identities = Object.freeze({
  manager: { identifier: 'cn.uniqueness.quote777.manager', productName: '记账器母版', binary: 'quote777-manager' },
  sales: { identifier: 'cn.uniqueness.quote777.sales', productName: '记账器子版', binary: 'quote777-sales' },
});
export const digest = bytes => createHash('sha256').update(bytes).digest('hex');
export const json = value => JSON.stringify(value, null, 2) + '\n';
export function requireDelivery(delivery) {
  if (!Object.hasOwn(identities, delivery)) throw Error('DELIVERY_REQUIRED: manager or sales');
  return identities[delivery];
}
function keys(value, allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !allowed.includes(k))) throw Error('CONFIG_FIELDS_NOT_ALLOWED');
}
export function connection(value) {
  keys(value, ['url', 'certificate_pem', 'certificate_sha256']);
  if (![value.url, value.certificate_pem, value.certificate_sha256].every(s => typeof s === 'string') || value.certificate_pem.length > 60000) throw Error('CONNECTION_INVALID');
  const url = new URL(value.url);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw Error('HTTPS_ORIGIN_REQUIRED');
  if (!/^-----BEGIN CERTIFICATE-----\r?\n[\s\S]+\r?\n-----END CERTIFICATE-----\s*$/.test(value.certificate_pem) || value.certificate_pem.includes('PRIVATE KEY') || (value.certificate_pem.match(/BEGIN CERTIFICATE/g) ?? []).length !== 1) throw Error('PUBLIC_CERTIFICATE_REQUIRED');
  const certificate = new X509Certificate(value.certificate_pem);
  const pin = value.certificate_sha256.toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(pin) || digest(certificate.raw) !== pin) throw Error('CERTIFICATE_PIN_MISMATCH');
  return { url: url.origin, certificate_pem: value.certificate_pem.trim() + '\n', certificate_sha256: pin };
}
export function publicConnection(value) {
  if (value?.schema === '777-desktop-bootstrap-v1') {
    keys(value, ['schema', 'delivery', 'connection', 'username', 'password', 'ticket']);
  } else {
    keys(value, ['schema', 'connection']);
    if (value.schema !== '777-public-connection-v1') throw Error('PUBLIC_CONFIG_SCHEMA_INVALID');
  }
  return { schema: '777-public-connection-v1', connection: connection(value.connection) };
}
export async function readJson(file, limit = 1024 * 1024) {
  const stat = await fs.stat(file);
  if (!stat.isFile() || stat.size > limit) throw Error('JSON_FILE_INVALID');
  return JSON.parse((await fs.readFile(file, 'utf8')).replace(/^\uFEFF/, ''));
}
export async function noLinks(file) {
  for (let p = path.resolve(file);; p = path.dirname(p)) {
    try { if ((await fs.lstat(p)).isSymbolicLink()) throw Error('DEPLOYMENT_PATH_SYMLINK'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (p === path.dirname(p)) break;
  }
}
export async function writeNew(file, value) {
  await noLinks(file);
  await fs.mkdir(path.dirname(file), { recursive: true });
  await noLinks(file);
  const handle = await fs.open(file, 'wx', 0o600);
  try { await handle.writeFile(json(value)); await handle.sync(); }
  finally { await handle.close(); }
}
export async function verifyRelease(directory) {
  const manifest = await readJson(path.join(directory, 'release.json'));
  const identity = requireDelivery(manifest.delivery);
  if (manifest.schema !== '777-desktop-release-v1' || manifest.identifier !== identity.identifier || manifest.profile_compatibility_epoch !== 1 || manifest.verification !== false || manifest.release !== true || !/^\d+\.\d+\.\d+$/.test(manifest.version) || manifest.service_protocol !== '777-service-v1' || !['777-device-auth-v1','777-auto-enrollment-v1'].includes(manifest.device_protocol) || !Array.isArray(manifest.files) || manifest.files.length < 3) throw Error('RELEASE_MANIFEST_INVALID');
  const names = new Set();
  for (const file of manifest.files) {
    if (!file.name || (file.name!=='automatic/package.json' && (path.basename(file.name) !== file.name || /[\\/]/.test(file.name))) || names.has(file.name) || !/^[a-f0-9]{64}$/.test(file.sha256)) throw Error('RELEASE_FILE_INVALID');
    names.add(file.name);
    const bytes = await fs.readFile(path.join(directory, file.name));
    if (bytes.length !== file.bytes || digest(bytes) !== file.sha256) throw Error('RELEASE_HASH_MISMATCH');
  }
  if (!names.has('connection.json') || !names.has(identity.binary + '.exe') || !names.has(manifest.installer) || !manifest.installer.endsWith('-setup.exe')) throw Error('RELEASE_FILES_MISSING');
  const config = publicConnection(await readJson(path.join(directory, 'connection.json')));
  if (digest(Buffer.from(json(config))) !== manifest.connection_sha256) throw Error('RELEASE_CONNECTION_MISMATCH');
  if(manifest.device_protocol==='777-auto-enrollment-v1') {
    if(!names.has('automatic/package.json')||names.has('enroll.ps1')) throw Error('RELEASE_AUTOMATIC_PACKAGE_MISSING');
    const p=await readJson(path.join(directory,'automatic/package.json'),131072);
    if(p.manifest.package_id!==manifest.package_id||p.manifest.delivery!==manifest.delivery||p.manifest.release_version!==manifest.version||p.profile.primary_url!==config.connection.url||p.profile.tls.certificate_sha256!==config.connection.certificate_sha256)throw Error('RELEASE_AUTOMATIC_PACKAGE_CONFLICT');
  }
  return { manifest, config };
}
export function compatibleRollback(current, previous) {
  requireDelivery(current.delivery); requireDelivery(previous.delivery);
  for (const key of ['schema', 'delivery', 'identifier', 'profile_compatibility_epoch', 'service_protocol', 'device_protocol', 'connection_sha256']) {
    if (current[key] !== previous[key]) throw Error('ROLLBACK_COMPATIBILITY_CONFLICT: ' + key);
  }
  return true;
}
export async function enroll(directory, grantFile, { localAppData = process.env.LOCALAPPDATA } = {}) {
  const { manifest, config } = await verifyRelease(directory);
  const grant = await readJson(grantFile, 65536);
  keys(grant, ['schema', 'delivery', 'connection', 'ticket']);
  if (grant.schema !== '777-desktop-bootstrap-v1' || grant.delivery !== manifest.delivery || !/^[A-Za-z0-9_-]{43}$/.test(grant.ticket ?? '')) throw Error('ENROLLMENT_ROLE_OR_TICKET_INVALID');
  if (json(connection(grant.connection)) !== json(config.connection)) throw Error('ENROLLMENT_SERVICE_CONFLICT');
  if (!localAppData || !path.isAbsolute(localAppData)) throw Error('LOCALAPPDATA_REQUIRED');
  // Stable across installer names, versions and install directories; matches native startup.
  const profile = path.join(localAppData, 'cn.uniqueness.quote777', manifest.delivery);
  await writeNew(path.join(profile, 'bootstrap.json'), { ...grant, connection: config.connection });
  return profile;
}
export function options(args, allowed) {
  const result = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i];
    if (!allowed.includes(key) || Object.hasOwn(result, key) || !args[i + 1] || args[i + 1].startsWith('--')) throw Error('ARGUMENT_INVALID: ' + key);
    result[key] = args[i + 1];
  }
  return result;
}
async function main(args) {
  const action = args.shift();
  if (action === 'export') {
    const a = options(args, ['--from', '--output']);
    if (!a['--from'] || !a['--output']) throw Error('export --from bootstrap.json --output connection.json');
    await writeNew(a['--output'], publicConnection(await readJson(a['--from'])));
    console.log('公开连接配置已导出；账号、密码、登记票据及草稿均未复制。');
  } else if (action === 'enroll') {
    if (process.platform !== 'win32') throw Error('ACTUAL_WINDOWS_REQUIRED');
    const a = options(args, ['--release', '--grant']);
    if (!a['--release'] || !a['--grant']) throw Error('enroll --release release-directory --grant one-device.json');
    await enroll(a['--release'], a['--grant']);
    console.log('登记材料已放入当前Windows用户的对应原生profile；请启动应用。');
  } else if (action === 'verify') {
    const a = options(args, ['--release']);
    const { manifest } = await verifyRelease(a['--release']);
    console.log(json({ delivery: manifest.delivery, version: manifest.version, files_verified: manifest.files.length }));
  } else if (action === 'check-rollback') {
    const a = options(args, ['--current', '--previous']);
    const current = await verifyRelease(a['--current']), previous = await verifyRelease(a['--previous']);
    compatibleRollback(current.manifest, previous.manifest);
    console.log('兼容性核对通过；尚未执行卸载或安装。按交付文档先保留profile并核对待核查请求。');
  } else throw Error('Use export, enroll, verify or check-rollback');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => { console.error(error.code ?? error.message); process.exitCode = 1; });
}
