import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { ignoreGeneratedOutput } from '../tools/package.mjs';

test('packages saved inside a selected source folder do not dirty later builds or hide source changes', async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), '777-output-location-'));
  const repository = path.join(temporary, 'source');
  await fs.mkdir(repository);
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repository, encoding: 'utf8' }).trim();
  try {
    git('init', '--quiet');
    await fs.writeFile(path.join(repository, 'source.ts'), 'original'); git('add', 'source.ts');
    const output = path.join(repository, '中文 [保存] !', 'manager-0.1.0-unique');
    await fs.mkdir(output, { recursive: true });
    await ignoreGeneratedOutput(output, repository);
    await fs.writeFile(path.join(output, 'installer.exe'), 'generated');
    await fs.writeFile(path.join(repository, 'source.ts'), 'changed');
    await fs.writeFile(path.join(repository, 'untracked.ts'), 'new source');
    const status = git('status', '--porcelain');
    assert(status.includes('AM source.ts'));
    assert(status.includes('?? untracked.ts'));
    assert(!status.includes('installer') && !status.includes('manager-0.1.0'));
    const relative = path.relative(repository, output).split(path.sep).join('/');
    assert.equal(git('-c', 'core.quotepath=false', 'check-ignore', '--', relative), relative);
    const exclude = path.join(repository, '.git/info/exclude');
    const before = await fs.readFile(exclude, 'utf8');
    const outside = path.join(temporary, 'external output'); await fs.mkdir(outside);
    await ignoreGeneratedOutput(outside, repository);
    assert.equal(await fs.readFile(exclude, 'utf8'), before);
    await assert.rejects(ignoreGeneratedOutput(output, repository), /PACKAGE_OUTPUT_NOT_EMPTY/);
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
});
