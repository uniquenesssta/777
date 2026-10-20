import { useEffect, useState } from "react";
import type { CustomerGroup } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { money, stamp } from "../state/format";
import { customerQueries } from "../state/customerMatches";
import { useCustomers } from "../state/useCustomers";
import { Button, Modal } from "../ui/components";
function Rows({app,group,onNavigate}:{app:Workbench;group:CustomerGroup;onNavigate?:()=>void}){
  return <>{group.orders.map(o=><div className="customer-order-row" key={o.order_id}><span>{o.details.order_ref||"未填写订单号"}</span><span>{stamp(o.created_at)}</span><strong>¥{money(o.income_cents)}</strong><span>{o.state==="void"?"已作废":"已保存"}</span><Button variant="ghost" disabled={app.busy||app.pending} onClick={()=>{onNavigate?.();void app.readOrder(o.order_id);}}>查看</Button>{app.can("edit_orders")&&o.state==="active"&&<Button variant="ghost" disabled={app.busy||app.pending} onClick={()=>{onNavigate?.();void app.beginEdit(o.order_id);}}>继续编辑</Button>}</div>)}</>;
}
export function CustomerMatches({app}:{app:Workbench}){
  const queries=customerQueries(app.draft.details);
  const [offset,setOffset]=useState(0),[open,setOpen]=useState(false);
  const queryKey=JSON.stringify(queries);
  useEffect(()=>setOffset(0),[queryKey]);
  useEffect(()=>{if(app.matchRequest)setOpen(true);},[app.matchRequest]);
  const {data,error,loading}=useCustomers(app,queries,offset,undefined,0,queries.length>0,app.matchRequest,250);
  if(!queries.length)return null;
  const choose=(g:CustomerGroup)=>{app.chooseCustomer(g);setOpen(false);};
  const separate=()=>{app.chooseNewCustomer();setOpen(false);};
  const content=<section className="customer-match" aria-label="匹配客户与订单">
    {loading&&<small>查找已有客户与订单…</small>}{error&&<p role="alert">{error}</p>}
    {data?.groups.map(g=><div key={g.group_id}><div className="customer-match-heading"><strong>{g.details.customer||"未填写客户"}</strong><span>微信 {g.details.wechat||"未填写"} · {g.total} 笔订单</span><Button variant="outline" disabled={app.busy||app.pending} onClick={()=>choose(g)}>{app.draft.editing?"关联到该客户":"该客户新建订单"}</Button></div><Rows app={app} group={g} onNavigate={()=>setOpen(false)}/>{g.total>20&&<small>显示最近20笔，可在订单记录按客户查看全部订单。</small>}</div>)}
    {!!data&&data.total>0&&<Button variant="ghost" disabled={app.busy||app.pending} onClick={separate}>这些不是同一客户，单独建立客户记录</Button>}
    {data?.total===0&&<div className="customer-match-heading"><span>未找到匹配记录，可将填写信息作为新客户。</span><Button variant="ghost" onClick={separate}>作为新客户</Button></div>}
    {!!data&&(offset>0||data.has_more)&&<div className="button-pair"><Button disabled={!offset} variant="ghost" onClick={()=>setOffset(Math.max(0,offset-20))}>上一页客户</Button><Button disabled={!data.has_more} variant="ghost" onClick={()=>setOffset(offset+20)}>下一页客户</Button></div>}
  </section>;
  return <>
    {!open&&content}
    {!!data?.total&&!open&&<Button variant="ghost" onClick={()=>setOpen(true)}>选择匹配客户与订单</Button>}
    <Modal className="customer-picker" open={open} onOpenChange={setOpen} title="选择匹配客户与订单" description="同一客户的新订单请选择“该客户新建订单”；修改原订单请选择“继续编辑”。">
      {content}
      <div className="dialog-actions"><Button variant="outline" onClick={()=>setOpen(false)}>返回报价</Button></div>
    </Modal>
  </>;
}
