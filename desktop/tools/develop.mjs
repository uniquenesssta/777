import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { prepareFonts } from './prepare-fonts.mjs';
const args=process.argv.slice(2);
const development=args[0]==='dev' && !args.some(a=>['--help','-h','--version','-V'].includes(a));
const script=fileURLToPath(new URL('../../tools/p07_dev_host.py',import.meta.url));
const cli=fileURLToPath(new URL('../node_modules/@tauri-apps/cli/tauri.js',import.meta.url));
if(development)await prepareFonts();
const child=development
  ? spawn(process.platform==='win32'?'py':'python3',[...(process.platform==='win32'?['-3']:[]),script,'--desktop','--',...args.slice(1)],{stdio:['pipe','inherit','inherit'],env:{...process.env,CARGO_BUILD_JOBS:process.env.CARGO_BUILD_JOBS??'1',QUOTE777_NODE:process.execPath}})
  : spawn(process.execPath,[cli,...args],{stdio:'inherit'});
child.on('error',e=>{console.error(e.message);process.exitCode=1;});
child.on('exit',code=>{child.stdin?.destroy();process.exitCode=code??1;});
child.stdin?.on('error',error=>{if(error.code!=='EPIPE' && error.code!=='ERR_STREAM_DESTROYED'){console.error(error.message);process.exitCode=1;}});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{
  if(development && child.exitCode===null && !child.stdin.destroyed && !child.stdin.writableEnded)child.stdin.end('\n'); // Cooperative request, never Windows TerminateProcess.
  else if(process.platform!=='win32')child.kill(signal);
});
