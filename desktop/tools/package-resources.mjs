// One explicit resource inventory for Tauri and the signed installed payload.
import fs from 'node:fs/promises';
import path from 'node:path';

function targetPath(value) {
  if (!value || value.includes('\\') || path.posix.isAbsolute(value) || value.includes(':') ||
      value.split('/').some(part => !part || part === '.' || part === '..')) throw Error('PACKAGE_RESOURCE_TARGET_INVALID');
  return value;
}

export async function resourceInventory(resources, base, {includeEnvelope = false} = {}) {
  const files = {};
  async function add(source, destination) {
    const stat = await fs.lstat(source);
    if (stat.isSymbolicLink()) throw Error('PACKAGE_RESOURCE_LINK_FORBIDDEN');
    if (stat.isDirectory()) {
      for (const name of await fs.readdir(source)) await add(path.join(source, name), destination.replace(/\/$/, '') + '/' + name);
    } else if (stat.isFile()) {
      targetPath(destination);
      if (Object.hasOwn(files, destination)) throw Error('PACKAGE_RESOURCE_TARGET_CONFLICT');
      files[destination] = source;
    } else throw Error('PACKAGE_RESOURCE_INVALID');
  }
  for (const [source, destination] of Object.entries(resources)) {
    if (includeEnvelope || destination !== 'automatic/package.json') await add(path.resolve(base, source), destination);
  }
  return files;
}

export function relativeResourcePath(source, project, paths = path) {
  const relative = paths.relative(project, source);
  // In particular, win32.relative keeps an absolute path across drive letters.
  // Tauri's resource normalizer drops drive prefixes: never pass such a path.
  if (!relative || paths.isAbsolute(relative) || relative.includes(':')) throw Error('PACKAGE_RESOURCE_DRIVE_CONFLICT');
  return relative.split(paths.sep).join('/');
}

export async function stageResources(resources, project, directory) {
  relativeResourcePath(directory, project);
  const files = await resourceInventory(resources, project, {includeEnvelope: true});
  const staged = {};
  for (const [destination, source] of Object.entries(files)) {
    const target = path.join(directory, ...destination.split('/'));
    await fs.mkdir(path.dirname(target), {recursive: true});
    await fs.copyFile(source, target);
    staged[relativeResourcePath(target, project)] = destination;
  }
  return staged;
}
