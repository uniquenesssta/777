import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const script=fileURLToPath(new URL('../../tools/p07_dev_host.py',import.meta.url));
const child=spawn(process.platform==='win32'?'py':'python3', [...(process.platform==='win32'?['-3']:[]),script,'--frontend'],{stdio:'inherit'});
child.on('error',e=>{console.error(e.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
