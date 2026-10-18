import { useState } from 'react';
import { Button } from '../../ui/components';
import { defaults, permissionCatalog, togglePermission, type Delivery } from '../../state/permissions';
import { PackageTarget, type TargetState } from './PackageTarget';

type Props = {
  disabled:boolean; ready:boolean; target:TargetState; onTarget:(value:TargetState)=>void;
  output:string; version:string; runtime:string;
  onOutput:()=>void; onVersion:(value:string)=>void; onRuntime:(value:string)=>void;
  onPackage:(delivery:Delivery,permissions:string[])=>void;
};
export function PackageChoices(p:Props) {
  const [delivery,setDelivery]=useState<Delivery>('manager');
  const [policies,setPolicies]=useState({manager:defaults('manager'),sales:defaults('sales')});
  const selected=policies[delivery];
  const versionParts=p.version.split('.').map(Number);
  return <section className="card developer-card package-choices" data-node-id="105:1982">
    <h2>应用封包</h2>
    <fieldset disabled={p.disabled}><legend>1 选择版本</legend><div className="package-choice-row">
      {(['manager','sales'] as const).map(value=><label key={value}><input type="radio" name="package-delivery" checked={delivery===value} onChange={()=>setDelivery(value)}/>{value==='manager'?'母版':'子版'}</label>)}
    </div></fieldset>
    <fieldset disabled={p.disabled}><legend>2 选择功能与显示</legend><div className="package-permissions">
      {permissionCatalog.map(item=><label key={item.id} className={item.admin&&delivery==='sales'?'muted':''}>
        <input type="checkbox" checked={selected.includes(item.id)} disabled={item.required||(item.admin&&delivery==='sales')} onChange={e=>setPolicies({...policies,[delivery]:togglePermission(selected,item.id,e.target.checked)})}/>
        <span>{item.label}{item.required?' · 基础功能':''}{item.admin&&delivery==='sales'?' · 仅母版':''}</span>
      </label>)}
    </div></fieldset>
    <small className="muted">未选择的功能不显示，也不能调用。需要关联功能时会一并勾选；关闭成本与利润时也会关闭价格维护。</small>
    <fieldset disabled={p.disabled}><legend>3 选择封包配置</legend>
      <PackageTarget disabled={p.disabled} onChange={p.onTarget}/>
      <div className="package-choice-row"><span>输出位置</span><Button variant="outline" onClick={p.onOutput}>选择文件夹</Button></div>
      <p className="developer-job-path">{p.output||'使用默认输出位置'}</p>
      <div className="package-choice-row"><span>版本 {p.version}</span><Button variant="ghost" onClick={()=>p.onVersion(`${versionParts[0]||0}.${versionParts[1]||0}.${(versionParts[2]||0)+1}`)}>递增修订版</Button></div>
      <div className="package-choice-row">{[['downloadBootstrapper','联网安装'],['offlineInstaller','离线完整包']].map(([value,label])=><label key={value}><input type="radio" name="package-runtime" checked={p.runtime===value} onChange={()=>p.onRuntime(value)}/>{label}</label>)}</div>
    </fieldset>
    <Button disabled={p.disabled||!p.ready||!p.target.verified} onClick={()=>p.onPackage(delivery,[...selected])}>按所选权限封包{delivery==='manager'?'母版':'子版'}</Button>
    <small className="muted">两个正式版本均无登录、退出、连接或登记提示。内部异常仅记录日志。首次使用前仍需由部署人员完成设备登记。</small>
  </section>;
}
