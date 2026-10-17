import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const child = spawn(process.platform === 'win32' ? 'py' : 'python3', [
  ...(process.platform === 'win32' ? ['-3'] : []), '-m', 'deployment.host', ...process.argv.slice(2),
], { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' } });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
