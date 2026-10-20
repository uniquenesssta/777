import {useState} from 'react';
import {Button} from '../../ui/components';
import {defaults,permissionCatalog,togglePermission,type Delivery} from '../../state/permissions';
import {request} from '../../bridge';
import {developer,usePackaging} from './usePackaging';
import {PackageTasks} from './PackageTasks';
import check from './assets/check.svg';
import type {PackageConfiguration} from './types';
export function PackageChoices({onMaintenance}:{onMaintenance:()=>void}){
  const {state,busy,error,building,run,setState}=usePackaging();
  const [delivery,setDelivery]=useState<Delivery>('manager'),[policies,setPolicies]=useState({manager:defaults('manager'),sales:defaults('sales')});
  const [draft,setDraft]=useState<{output:string;version:string;runtime:string}|null>(null);
  const prefs=draft??state?.preferences??{output:'',version:'0.1.0',runtime:'downloadBootstrapper'};
  const selected=policies[delivery],disabled=busy||building;
  const change=(value:Partial<typeof prefs>)=>setDraft({...prefs,...value});
  const title=delivery==='manager'?'母版':'子版';
  const label=(item:typeof permissionCatalog[number])=>item.id==='settings'?(delivery==='sales'?'存储设置（只读）':'存储设置'):item.label;
  async function pack(){await run(async()=>{await developer('save_package',prefs);setState(await developer<PackageConfiguration>('package',{delivery,permissions:selected}));});}
  return <div className="packaging-workspace" data-node-id={delivery==='manager'?'113:2205':'113:2206'}>
    <div className="package-columns">
      <section className="card package-panel">
        <h2>选择版本与功能</h2>
        <div className="package-editions" role="group" aria-label="版本类型">{(['manager','sales'] as const).map(kind=><Button key={kind} aria-pressed={delivery===kind} variant={delivery===kind?'primary':'outline'} disabled={disabled} onClick={()=>setDelivery(kind)}>{kind==='manager'?'母版':'子版'}</Button>)}</div>
        <small className="muted">{delivery==='manager'?'母版 · 包含后台自动部署与同步':'子版 · 仅安装业务客户端'}</small>
        <fieldset className="package-permission-list" disabled={disabled}><legend className="sr-only">功能权限</legend>{permissionCatalog.filter(p=>delivery==='manager'||!p.admin).map(item=><label className="package-permission" key={item.id}>
          <input type="checkbox" checked={selected.includes(item.id)} disabled={item.required} onChange={e=>setPolicies({...policies,[delivery]:togglePermission(selected,item.id,e.target.checked)})}/>
          <span className="package-checkbox" aria-hidden="true">{selected.includes(item.id)&&<img src={check} width="12" height="12" alt=""/>}</span>
          <span>{label(item)}{item.required?' · 基础功能':''}</span>
        </label>)}</fieldset>
        <small className="muted">勾选后显示对应功能；关联项自动一并选择。</small>
        <div className="package-options">
          <h3>封包选项</h3>
          <div className="package-option-row"><span>版本 {prefs.version}</span><Button variant="ghost" disabled={disabled} onClick={()=>{const a=prefs.version.split('.').map(Number);change({version:`${a[0]||0}.${a[1]||0}.${(a[2]||0)+1}`});}}>递增修订版</Button></div>
          <div className="package-actions">{[['downloadBootstrapper','联网安装'],['offlineInstaller','含离线运行库']].map(([value,text])=><Button key={value} disabled={disabled} aria-pressed={prefs.runtime===value} variant={prefs.runtime===value?'primary':'outline'} onClick={()=>change({runtime:value})}>{text}</Button>)}</div>
          <small className="muted">此选项仅决定安装运行库的方式。</small>
          <div className="package-option-row"><h3>输出位置</h3><Button variant="outline" disabled={disabled} onClick={()=>void run(async()=>{const v=await request<{directory:string|null}>('pick_directory',{target:'developer_output'});if(v.directory)change({output:v.directory});})}>选择文件夹</Button></div>
          <p className="package-path muted">{prefs.output||'使用默认输出位置'}</p>
        </div>
      </section>
      <section className="card package-panel package-summary">
        <h2>本次封包</h2><h3>{title}</h3>
        <p>{permissionCatalog.filter(p=>selected.includes(p.id)).map(label).join('、')}。</p>
        <small className="muted">{delivery==='manager'?'安装时自动配置后台，接入同一份业务数据。':'安装后自动接入业务数据。'}</small>
        <small className="muted">功能以本次勾选为准。</small>
        <Button disabled={disabled||!state?.issuer?.ready} onClick={()=>void pack()}>封包{title}</Button>
        {state&&!state.issuer?.ready&&<><p>尚未获得 4.23 的封包授权，完成后即可封包。</p><Button variant="outline" disabled={disabled} onClick={onMaintenance}>完成封包授权</Button></>}
        <small className="muted">登录、退出登录和内部连接提示始终隐藏。</small>
      </section>
    </div>
    {error&&<p className="inline-error" role="alert">{error}</p>}
    <PackageTasks job={state?.job??null} disabled={busy} onAction={op=>void run(async()=>setState(await developer<PackageConfiguration>(op)))}/>
  </div>;
}
