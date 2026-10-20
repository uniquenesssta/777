import {useEffect,useRef,useState} from 'react';
import {Button,Input} from '../../ui/components';
import type {Workbench} from '../../state/useWorkbench';
import {money,stamp} from '../../state/format';
import {readOrders,cleanupError,type CleanupPage,type CleanupOrder,type DeleteChoice} from './api';
import {DeleteOrderDialog} from './DeleteOrderDialog';
import './orderCleanup.css';
export function OrderCleanup({app}:{app:Workbench}){
 const [query,setQuery]=useState('');const [filter,setFilter]=useState('');const [offset,setOffset]=useState(0);const [history,setHistory]=useState(false);const [page,setPage]=useState<CleanupPage|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [choice,setChoice]=useState<DeleteChoice|null>(null);const [refresh,setRefresh]=useState(0);const epoch=useRef(0);
 useEffect(()=>{const id=++epoch.current;setBusy(true);setError('');setPage(null);readOrders(filter,offset,history).then(v=>{if(id===epoch.current)setPage(v);}).catch(e=>{if(id===epoch.current)setError(cleanupError(e));}).finally(()=>{if(id===epoch.current)setBusy(false);});return()=>{epoch.current++;};},[filter,offset,history,refresh]);
 const disabled=busy||app.busy||!!app.pending;
 function choose(order:CleanupOrder){if(!page)return;setChoice({ledger_id:page.ledger_id,request_id:crypto.randomUUID(),order,reason:''});}
 return <section className="card order-cleanup" aria-label="订单清理">
  <div className="section-heading"><h2>订单清理</h2><Button variant="ghost" disabled={disabled} onClick={()=>setRefresh(v=>v+1)}>重新读取</Button></div>
  <div className="cleanup-identity"><strong>{app.connection?.url??'尚未连接后台'}</strong><small>账本：{page?.ledger_id??'待读取'}</small></div>
  <div className="cleanup-toolbar"><div className="cleanup-actions">{[false,true].map(v=><Button key={String(v)} variant={history===v?'primary':'ghost'} disabled={disabled} onClick={()=>{setHistory(v);setOffset(0);}}>{v?'删除记录':'现有订单'}</Button>)}</div><form onSubmit={e=>{e.preventDefault();setFilter(query.trim());setOffset(0);setRefresh(v=>v+1);}}><Input aria-label="查找清理订单" maxLength={256} placeholder="淘宝 ID、微信号或订单号" value={query} onChange={e=>setQuery(e.target.value)}/><Button variant="outline" disabled={disabled} type="submit">查找</Button></form></div>
  <div className="cleanup-list" aria-busy={busy}>{page?.orders.map(order=><article className="cleanup-row" key={order.order_id}><div><strong>{order.details.customer||'未填写客户'}</strong><span>订单号：{order.details.order_ref||'—'} · 微信：{order.details.wechat||'—'}</span><small>{order.order_id}</small>{history&&<><span>原因：{order.reason}</span><small>{stamp(order.deleted_at??'')} · 操作账号：{order.deleted_by}</small></>}</div><div className="cleanup-row-action"><b>{money(order.income_cents)}</b>{!history&&<Button variant="danger" disabled={disabled} onClick={()=>choose(order)}>删除订单</Button>}</div></article>)}{!busy&&page?.orders.length===0&&<p className="muted">{history?'暂无删除记录':'没有找到订单'}</p>}{busy&&<p className="muted">正在读取</p>}</div>
  {error&&<p role="alert" className="inline-error">{error}</p>}
  <div className="cleanup-actions"><span className="muted">共 {page?.total??0} 笔</span><Button variant="outline" disabled={disabled||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-20))}>上一页</Button><Button variant="outline" disabled={disabled||!page||offset+20>=page.total} onClick={()=>setOffset(v=>v+20)}>下一页</Button></div>
  {choice&&<DeleteOrderDialog choice={choice} onClose={()=>{setChoice(null);setRefresh(v=>v+1);}} onDeleted={()=>{setChoice(null);setOffset(0);setRefresh(v=>v+1);}}/>}
 </section>;
}
