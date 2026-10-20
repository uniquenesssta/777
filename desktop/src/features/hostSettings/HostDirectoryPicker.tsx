import { useEffect, useRef, useState } from 'react';
import { Button, Input, Modal } from '../../ui/components';
import { browseHost, hostError, type HostDirectories } from './api';
export function HostDirectoryPicker({ledgerId,initial,onSelect,onClose}:{ledgerId:string;initial:string;onSelect:(path:string)=>void;onClose:()=>void}) {
  const [listing,setListing]=useState<HostDirectories|null>(null);
  const [path,setPath]=useState(initial); const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  const epoch=useRef(0);
  async function browse(next:string) {
    const id=++epoch.current;setBusy(true);setError('');
    try {const result=await browseHost(ledgerId,next);if(id===epoch.current){setListing(result);setPath(result.path);}}
    catch(e){if(id===epoch.current)setError(hostError(e));}
    finally{if(id===epoch.current)setBusy(false);}
  }
  useEffect(()=>{void browse(initial);return()=>{epoch.current++;};},[ledgerId]);
  return <Modal open title="选择 Host 上的备份文件夹" onOpenChange={v=>{if(!v)onClose();}} className="host-folder-dialog">
    <p className="muted">这里列出的是服务器文件夹。共享目录可粘贴完整路径后打开。</p>
    <div className="host-folder-path"><Input aria-label="Host 文件夹路径" value={path} onChange={e=>setPath(e.target.value)} disabled={busy}/><Button variant="outline" disabled={busy||!path.trim()} onClick={()=>void browse(path)}>打开</Button></div>
    <div className="host-folder-roots">{listing?.roots.map(root=><Button key={root} variant="ghost" disabled={busy} onClick={()=>void browse(root)}>{root}</Button>)}<Button variant="outline" disabled={busy||!listing?.parent} onClick={()=>void browse(listing!.parent!)}>上一级</Button></div>
    <div className="host-folder-list" aria-label="Host 子文件夹" aria-busy={busy}>{listing?.directories.map(dir=><Button key={dir} variant="ghost" disabled={busy} onClick={()=>void browse(dir)}>{dir.split(/[\\/]/).filter(Boolean).at(-1)}</Button>)}{listing&&!listing.directories.length&&<p className="muted">此文件夹没有子文件夹。</p>}</div>
    {listing?.truncated&&<p className="muted">子文件夹较多，仅显示前 500 项；可输入完整路径打开。</p>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    <div className="dialog-actions"><Button variant="outline" onClick={onClose}>取消</Button><Button disabled={busy||!listing||!!error} onClick={()=>onSelect(listing!.path)}>选择当前文件夹</Button></div>
  </Modal>;
}
