import {Button} from '../../ui/components';
import {permissionCatalog} from '../../state/permissions';
import type {PackageJob} from './types';
export function PackageTasks({job,disabled,onAction}:{job:PackageJob|null;disabled:boolean;onAction:(op:string)=>void}){
  const building=job?.state==='running'||job?.state==='cancelling';
  const label=!job?'封包任务':({running:'正在封包',cancelling:'正在取消',cancelled:'已取消封包',failed:'封包未完成',succeeded:'封包完成'})[job.state];
  return <section className="card package-panel" data-node-id="113:2209" aria-live="polite">
    <h2>{label}</h2>
    {!job?<p className="muted">尚未开始</p>:<>
      <p>{job.delivery==='manager'?'母版':'子版'} · {job.version}</p>
      {job.state==='failed'&&<p>所选功能已保留，尚未生成可分发安装包。</p>}
      {job.state==='cancelled'&&<p>本次未交付安装包，可重新开始。</p>}
      {job.state==='succeeded'&&<><p>已包含：{permissionCatalog.filter(p=>job.permissions?.includes(p.id)).map(p=>p.label).join('、')}。</p><p className="package-path">{job.output}</p></>}
      {building&&<p className="muted">正在准备程序与发行，完成前不会提供可分发安装包。</p>}
      <div className="package-actions">
        {building&&<Button variant="outline" disabled={disabled||job.state==='cancelling'} onClick={()=>onAction('cancel')}>取消封包</Button>}
        {job.state==='failed'&&<Button disabled={disabled} onClick={()=>onAction('retry_package')}>重试本次封包</Button>}
        {job.state==='succeeded'&&<Button disabled={disabled} onClick={()=>onAction('open_output')}>打开产物文件夹</Button>}
        {(job.state==='failed'||job.state==='cancelled')&&<Button variant="outline" disabled={disabled} onClick={()=>onAction('open_logs')}>打开本次日志</Button>}
      </div>
      {!!job.lines.length&&<details><summary>查看构建日志</summary><pre className="developer-log">{job.lines.join('\n')}</pre></details>}
    </>}
  </section>;
}
