import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { X509Certificate } from 'node:crypto';
import { bundleConfig, installerHooks } from '../tools/package.mjs';
import { connection, compatibleRollback, digest, enroll, identities, json, options, publicConnection, requireDelivery, verifyRelease, writeNew } from '../tools/deployment.mjs';

const pem = await fs.readFile(new URL('./fixtures/service-cert.pem', import.meta.url), 'utf8');
const conn = { url: 'https://localhost:18477', certificate_pem: pem, certificate_sha256: digest(new X509Certificate(pem).raw) };
const config = publicConnection({ schema: '777-public-connection-v1', connection: conn });
async function fixture(delivery = 'sales') {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), '777-package-test-'));
  const release = path.join(root, 'release'); await fs.mkdir(release);
  const binary = identities[delivery].binary + '.exe', installer = 'synthetic-setup.exe';
  await fs.writeFile(path.join(release, binary), 'synthetic, not a native executable');
  await fs.writeFile(path.join(release, installer), 'synthetic, not an installer');
  await fs.writeFile(path.join(release, 'connection.json'), json(config));
  const files = [];
  for (const name of [binary, installer, 'connection.json']) {
    const bytes = await fs.readFile(path.join(release, name)); files.push({ name, bytes: bytes.length, sha256: digest(bytes) });
  }
  const manifest = { schema: '777-desktop-release-v1', delivery, identifier: identities[delivery].identifier, version: '0.1.0',
    profile_compatibility_epoch: 1, service_protocol: '777-service-v1', device_protocol: '777-device-auth-v1',
    connection_sha256: digest(Buffer.from(json(config))), release: true, verification: false, installer, files };
  await writeNew(path.join(release, 'release.json'), manifest);
  return { root, release, manifest, close: () => fs.rm(root, { recursive: true, force: true }) };
}
test('export strips development secrets and rejects unapproved configuration fields', () => {
  const result = publicConnection({ schema: '777-desktop-bootstrap-v1', delivery: 'development', username: 'admin', password: 'never-export', ticket: 'never-export', connection: conn });
  assert.equal(json(result), json(config));
  assert(!json(result).includes('never-export'));
  assert.throws(() => publicConnection({ ...result, role: 'admin' }));
  assert.throws(() => connection({ ...conn, url: 'http://localhost' }));
  assert.throws(() => connection({ ...conn, certificate_sha256: '0'.repeat(64) }));
  assert.throws(() => connection({ ...conn, certificate_pem: pem + '\n-----BEGIN PRIVATE KEY-----\nsecret' }));
});
test('release type is explicit and generated installers keep both roles isolated', () => {
  for (const value of ['', undefined, 'verification', 'manager,sales']) assert.throws(() => requireDelivery(value));
  const a = bundleConfig('manager', '0.1.0', 'manager.nsh'), b = bundleConfig('sales', '0.1.0', 'sales.nsh');
  assert.notEqual(a.identifier, b.identifier); assert.notEqual(a.mainBinaryName, b.mainBinaryName);
  assert.equal(a.bundle.windows.nsis.installMode, 'currentUser');
  assert.equal(a.bundle.windows.webviewInstallMode.type, 'offlineInstaller');
  assert.equal(a.bundle.windows.allowDowngrades, false);
  assert.match(installerHooks('manager'), /quote777-sales\.exe/);
  assert.throws(() => bundleConfig('sales', '0.1.0;injection', 'x'));
  assert.throws(() => options(['--delivery', 'sales', '--features', 'verification'], ['--delivery']));
  assert.throws(() => options(['--delivery', 'sales', '--delivery', 'manager'], ['--delivery']));
});
test('release verification rejects corruption and path traversal before enrollment', async () => {
  const f = await fixture();
  try {
    await verifyRelease(f.release);
    await fs.appendFile(path.join(f.release, identities.sales.binary + '.exe'), 'tampered');
    await assert.rejects(verifyRelease(f.release), /RELEASE_HASH_MISMATCH/);
    f.manifest.files[0].name = '../outside';
    await fs.writeFile(path.join(f.release, 'release.json'), json(f.manifest));
    await assert.rejects(verifyRelease(f.release), /RELEASE_FILE_INVALID/);
  } finally { await f.close(); }
});
test('enrollment refuses other role/service and preserves device and pending records', async () => {
  const f = await fixture();
  try {
    const grantFile = path.join(f.root, 'one-device.json');
    const grant = { schema: '777-desktop-bootstrap-v1', delivery: 'sales', connection: conn, ticket: 'a'.repeat(43) };
    const localAppData = path.join(f.root, 'local');
    const profile = path.join(localAppData, 'cn.uniqueness.quote777', 'sales');
    await fs.mkdir(profile, { recursive: true });
    await fs.writeFile(path.join(profile, 'device.bin'), 'protected-device'); await fs.writeFile(path.join(profile, 'pending.bin'), 'pending-original');
    await fs.writeFile(grantFile, json({ ...grant, delivery: 'manager' }));
    await assert.rejects(enroll(f.release, grantFile, { localAppData }), /ENROLLMENT_ROLE/);
    await fs.writeFile(grantFile, json({ ...grant, connection: { ...conn, url: 'https://localhost:18478' } }));
    await assert.rejects(enroll(f.release, grantFile, { localAppData }), /ENROLLMENT_SERVICE/);
    await fs.writeFile(grantFile, json(grant));
    assert.equal(await enroll(f.release, grantFile, { localAppData }), profile);
    assert.equal(await fs.readFile(path.join(profile, 'device.bin'), 'utf8'), 'protected-device');
    assert.equal(await fs.readFile(path.join(profile, 'pending.bin'), 'utf8'), 'pending-original');
    await assert.rejects(enroll(f.release, grantFile, { localAppData }), /EEXIST/);
  } finally { await f.close(); }
});
test('rollback permits only the same role, service and profile compatibility epoch', () => {
  const manifest = { schema: '777-desktop-release-v1', delivery: 'manager', identifier: identities.manager.identifier, profile_compatibility_epoch: 1, service_protocol: '777-service-v1', device_protocol: '777-device-auth-v1', connection_sha256: 'same' };
  assert.equal(compatibleRollback(manifest, { ...manifest, version: '0.0.1' }), true);
  for (const change of [{ delivery: 'sales' }, { identifier: identities.sales.identifier }, { profile_compatibility_epoch: 2 }, { connection_sha256: 'different' }]) assert.throws(() => compatibleRollback(manifest, { ...manifest, ...change }));
});
