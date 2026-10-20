import { useEffect, useRef, useState } from 'react';
import { Button, Field, Input } from '../../ui/components';
import type { Workbench } from '../../state/useWorkbench';
import { readHostBackup, saveHostBackup, hostError, type HostBackup } from './api';
import { HostDirectoryPicker } from './HostDirectoryPicker';
import './hostSettings.css';
export function HostBackupSettings({app}:{app:Workbench}) {
  const [current,setCurrent]=useState<HostBackup|null>(null);
  const [directory,setDirectory]=useState('');const [hour,setHour]=useState(23);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [saved,setSaved]=useState(false);const [picker,setPicker]=useState(false);
  const epoch=useRef(0);const locked=useRef(false);
  const source=`${app.connection?.url??''}|${app.connection?.certificate_sha256??''}|${app.session?.ledger_id??''}`;
  function accept(value:HostBackup){setCurrent(value);setDirectory(value.backup_dir);setHour(value.daily_hour);}
  async function read(){if(locked.current)return;locked.current=true;const id=epoch.current;setBusy(true);setError('');setSaved(false);
    try{const value=await readHostBackup();if(id===epoch.current)accept(value);}catch(e){if(id===epoch.current){setCurrent(null);setError(hostError(e));}}finally{locked.current=false;if(id===epoch.current)setBusy(false);}}
  useEffect(()=>{epoch.current++;setCurrent(null);setPicker(false);void read();return()=>{epoch.current++;};},[source]);
  async function save(){if(!current||locked.current)return;locked.current=true;const id=epoch.current;setBusy(true);setError('');setSaved(false);
    try{
      const applied=await saveHostBackup(current,directory,hour);
      const observed=await readHostBackup();
      if(observed.ledger_id!==applied.ledger_id||observed.revision!==applied.revision)throw {code:'HOST_BACKUP_READBACK_MISMATCH'};
      if(id===epoch.current){accept(observed);setSaved(true);}
    }catch(e){if(id===epoch.current)setError(hostError(e));}finally{locked.current=false;if(id===epoch.current)setBusy(false);}}
  const disabled=busy||app.busy||!!app.pending;
  return <section className="card host-backup-settings" aria-label="Host 备份设置">
    <div className="section-heading"><h2>当前 Host · 每日备份</h2><Button variant="ghost" disabled={disabled} onClick={()=>void read()}>重新读取</Button></div>
    <div className="host-backup-identity"><strong>{app.connection?.url??'尚未连接 Host'}</strong><small>账本：{current?.ledger_id??'待读取'}</small></div>
    {current&&<>
      <Field label="每日备份时间（北京时间）"><select aria-label="Host 每日备份时间" value={hour} disabled={disabled} onChange={e=>{setHour(Number(e.target.value));setSaved(false);}}>{Array.from({length:24},(_,h)=><option key={h} value={h}>{String(h).padStart(2,'0')}:00</option>)}</select></Field>
      <div className="host-backup-directory"><Field label="普通备份目录"><Input readOnly aria-label="Host 普通备份目录" value={directory}/></Field><Button variant="outline" disabled={disabled} onClick={()=>setPicker(true)}>选择 Host 文件夹</Button></div>
      <Field label="隐藏备份目录（固定）"><Input readOnly value={current.hidden_dir||'此 Host 尚未配置隐藏备份'}/></Field>
      <p className="muted">保存后应用到此 Host，后续备份使用新设置；原目录的已有备份保留。</p>
      <div className="host-backup-actions"><Button disabled={disabled||!directory||(directory===current.backup_dir&&hour===current.daily_hour)} onClick={()=>void save()}>应用到当前 Host</Button>{saved&&<span role="status">已应用，回读确认一致。</span>}</div>
    </>}
    {error&&<p className="inline-error" role="alert">{error}</p>}
    {picker&&current&&<HostDirectoryPicker ledgerId={current.ledger_id} initial={directory} onClose={()=>setPicker(false)} onSelect={p=>{setDirectory(p);setSaved(false);setPicker(false);}}/>}
  </section>;
}
