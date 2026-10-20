import {useState} from 'react';
import {Button} from '../ui/components';
import {DeveloperData} from './DeveloperData';
import {PackageChoices} from './packaging/PackageChoices';
import type {Workbench} from '../state/useWorkbench';
import './packaging/packaging.css';
export function DeveloperPage({app}:{app:Workbench}){
  const [tab,setTab]=useState<'packages'|'data'>('packages');
  return <section className="developer-page" aria-label="开发者工具">
    <div className="developer-title"><h1>{tab==='packages'?'应用封包':'开发数据'}</h1><p className="muted">制作母版、子版安装包，或切换开发数据；正式端不显示此入口。</p></div>
    <nav className="developer-workspace-tabs" aria-label="开发工作区">{([['packages','应用封包'],['data','开发数据']] as const).map(([id,label])=><Button key={id} aria-current={tab===id?'page':undefined} variant={tab===id?'primary':'ghost'} onClick={()=>setTab(id)}>{label}</Button>)}</nav>
    <div className="developer-content" hidden={tab!=='packages'}><PackageChoices/></div>
    {tab==='data'&&<DeveloperData app={app}/>}
  </section>;
}
