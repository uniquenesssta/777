import {useState} from 'react';
import {Button} from '../ui/components';
import {DeveloperData} from './DeveloperData';
import {PackageChoices} from './packaging/PackageChoices';
import {IssuerPage} from './packaging/IssuerPage';
import type {Workbench} from '../state/useWorkbench';
import './packaging/packaging.css';
export function DeveloperPage({app}:{app:Workbench}){
  const [tab,setTab]=useState<'packages'|'data'|'issuer'>('packages');
  return <section className="developer-page" aria-label="开发部署">
    <div className="developer-title"><h1>{tab==='packages'?'应用封包':tab==='data'?'开发数据':'发行维护'}</h1></div>
    <nav className="developer-workspace-tabs" aria-label="开发工作区">{([['packages','应用封包'],['data','开发数据'],['issuer','发行维护']] as const).map(([id,label])=><Button key={id} aria-current={tab===id?'page':undefined} variant={tab===id?'primary':'ghost'} onClick={()=>setTab(id)}>{label}</Button>)}</nav>
    <div className="developer-content" hidden={tab!=='packages'}><PackageChoices onMaintenance={()=>setTab('issuer')}/></div>
    {tab==='data'&&<DeveloperData app={app}/>}{tab==='issuer'&&<IssuerPage onReturn={()=>setTab('packages')}/>}
  </section>;
}
