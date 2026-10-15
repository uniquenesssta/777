// Build-time pinned assets. Product pages use only bundled local font files.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const manifest=JSON.parse(await fs.readFile(path.join(root,'resources/fonts.json'),'utf8'));
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function prepareFonts({directory=path.join(root,'public/fonts'),assets=manifest.assets,fetcher=fetch,log=console.log,download=true,signal}={}) {
  const missing=[];
  await fs.mkdir(directory,{recursive:true});
  for(const asset of assets) {
    signal?.throwIfAborted();
    if(path.basename(asset.file)!==asset.file)throw Error('FONT_FILENAME_INVALID');
    const target=path.join(directory,asset.file);
    try {
      const cached=await fs.readFile(target);
      if(hash(cached)!==asset.sha256 || cached.length!==asset.bytes)throw Error('FONT_CACHE_HASH_MISMATCH: '+asset.file);
      continue;
    } catch(error) {if(error.code!=='ENOENT')throw error;}
    if(!download) {
      missing.push(asset.file);
      log('缺少本地字体：'+asset.file+'；开发环境继续使用系统字体。');
      continue;
    }
    log('准备离线字体：'+asset.file);
    const response=await fetcher(asset.url,{signal:signal?AbortSignal.any([signal,AbortSignal.timeout(60000)]):AbortSignal.timeout(60000)});
    if(!response.ok)throw Error('FONT_DOWNLOAD_FAILED: '+asset.file);
    if(Number(response.headers.get('content-length')??0)>24*1024*1024)throw Error('FONT_TOO_LARGE');
    const bytes=Buffer.from(await response.arrayBuffer());
    if(bytes.length!==asset.bytes || hash(bytes)!==asset.sha256)throw Error('FONT_DOWNLOAD_HASH_MISMATCH: '+asset.file);
    const temporary=target+'.'+randomUUID()+'.tmp';
    try {await fs.writeFile(temporary,bytes,{flag:'wx'});await fs.rename(temporary,target);}
    finally {await fs.rm(temporary,{force:true});}
  }
  for(const name of new Set(assets.map(a=>a.license).filter(Boolean))) {
    if(path.basename(name)!==name)throw Error('FONT_LICENSE_INVALID');
    await fs.copyFile(path.join(root,'resources/licenses',name),path.join(directory,name));
  }
  return {missing};
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const download=!process.argv.slice(2).includes('--offline');
  const control=new AbortController();
  const cancel=()=>control.abort();
  process.once('SIGINT',cancel);process.once('SIGTERM',cancel);
  try {
    if(download)console.log('准备完整构建字体；缺失文件需联网下载，每个文件最多等待60秒。');
    const {missing}=await prepareFonts({download,signal:control.signal});
    if(missing.length)console.log('需要完整字体时运行：npm --prefix desktop run fonts:prepare');
  } catch(error) {
    if(control.signal.aborted) {console.error('已取消字体准备。');process.exitCode=130;}
    else {console.error('字体准备失败：'+(error instanceof Error?error.message:String(error)));process.exitCode=1;}
  } finally {process.removeListener('SIGINT',cancel);process.removeListener('SIGTERM',cancel);}
}
