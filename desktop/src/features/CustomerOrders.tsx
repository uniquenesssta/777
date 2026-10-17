import { useEffect, useState } from "react";
import type { CustomerListing, CustomerGroup } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { errorMessage } from "../bridge";
import { money, stamp } from "../state/format";
import { Button, Empty, Input } from "../ui/components";
function useCustomers(app:Workbench,query:string,offset:number,group?:string,orderOffset=0,enabled=true,refresh=0){
  const [data,setData]=useState<CustomerListing|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  useEffect(()=>{let alive=true;setData(null);setError("");if(!enabled){setLoading(false);return;}
    setLoading(true);const timer=setTimeout(()=>{app.customerOrders(query,offset,group,orderOffset).then(v=>{if(alive)setData(v);}).catch(e=>{if(alive)setError(errorMessage(e));}).finally(()=>{if(alive)setLoading(false);});},250);
    return()=>{alive=false;clearTimeout(timer);};
  },[query,offset,group,orderOffset,enabled,refresh,app.session?.subject,app.connection?.certificate_sha256]);
  return {data,error,loading};
}
function Rows({app,group}:{app:Workbench;group:CustomerGroup}){
  return <>{group.orders.map(o=><div className="customer-order-row" key={o.order_id}><span>{o.details.order_ref||"未填写订单号"}</span><span>{stamp(o.created_at)}</span><strong>¥{money(o.income_cents)}</strong><span>{o.state==="void"?"已作废":"已保存"}</span><Button variant="ghost" disabled={app.busy||app.pending} onClick={()=>void app.readOrder(o.order_id)}>查看</Button>{o.state==="active"&&<Button variant="ghost" disabled={app.busy||app.pending} onClick={()=>void app.beginEdit(o.order_id)}>继续编辑</Button>}</div>)}</>;
}
export function CustomerMatches({app,query}:{app:Workbench;query:string}){
  const [offset,setOffset]=useState(0);useEffect(()=>setOffset(0),[query]);
  const {data,error,loading}=useCustomers(app,query,offset,undefined,0,!!query.trim());
  if(!query.trim())return null;
  return <section className="customer-match" aria-label="匹配客户与订单">
    {loading&&<small>查找已有客户与订单…</small>}{error&&<p role="alert">{error}</p>}
    {data?.groups.map(g=><div key={g.group_id}><div className="customer-match-heading"><strong>{g.details.customer||"未填写客户"}</strong><span>微信 {g.details.wechat||"未填写"} · {g.total} 笔订单</span><Button variant="outline" disabled={app.busy||app.pending} onClick={()=>app.chooseCustomer(g)}>{app.draft.editing?"关联到该客户":"该客户新建订单"}</Button></div><Rows app={app} group={g}/>{g.total>20&&<small>显示最近20笔，可在订单记录按客户查看全部订单。</small>}</div>)}
    {!!data&&data.total>0&&<Button variant="ghost" disabled={app.busy||app.pending} onClick={()=>app.dispatch({type:"link_customer",details:app.draft.details,customer:{new_customer:true}})}>这些不是同一客户，单独建立客户记录</Button>}
    {data?.total===0&&<div className="customer-match-heading"><span>未找到匹配记录，可将填写信息作为新客户。</span><Button variant="ghost" onClick={()=>app.dispatch({type:"link_customer",details:app.draft.details,customer:{new_customer:true}})}>作为新客户</Button></div>}
    {!!data&&data.total>20&&<div className="button-pair"><Button disabled={!offset} variant="ghost" onClick={()=>setOffset(Math.max(0,offset-20))}>上一页客户</Button><Button disabled={offset+20>=data.total} variant="ghost" onClick={()=>setOffset(offset+20)}>下一页客户</Button></div>}
  </section>;
}
export function CustomerOrders({app,onAll}:{app:Workbench;onAll:()=>void}){
  const [input,setInput]=useState(""),[query,setQuery]=useState(""),[offset,setOffset]=useState(0),[group,setGroup]=useState<string>(),[orderOffset,setOrderOffset]=useState(0),[refresh,setRefresh]=useState(0);
  const {data,error,loading}=useCustomers(app,query,offset,group,orderOffset,true,refresh);
  return <section className="card orders-card" data-node-id="84:1646"><div className="section-heading"><h2>订单记录</h2><div className="button-pair"><Button variant="ghost" onClick={onAll}>全部订单</Button><Button>按客户查看</Button></div></div>
    <form className="order-filters" onSubmit={e=>{e.preventDefault();setQuery(input);setOffset(0);setGroup(undefined);setOrderOffset(0);setRefresh(v=>v+1);}}><Input aria-label="搜索客户" placeholder="客户 / 淘宝 ID、微信号或订单号" value={input} maxLength={256} onChange={e=>setInput(e.target.value)}/><Button type="submit">查找</Button>{group&&<Button variant="ghost" onClick={()=>{setGroup(undefined);setOrderOffset(0);}}>返回客户列表</Button>}</form>
    {loading&&<p>读取客户订单…</p>}{error&&<p role="alert">{error}</p>}{data?.total===0&&<Empty>暂无匹配的客户订单。</Empty>}
    <div className="customer-groups">{data?.groups.map(g=><section key={g.group_id} className="customer-group"><div className="customer-match-heading"><div><strong>{g.details.customer||"未填写客户"}</strong><small>微信号 {g.details.wechat||"未填写"}</small></div><span>有效订单 {g.active_count} 笔 · 合计 ¥{money(g.totals.income_cents)}</span><Button variant="outline" disabled={app.busy||app.pending} onClick={()=>app.chooseCustomer(g,true)}>{app.draft.editing?"关联到该客户":"该客户新建订单"}</Button></div><Rows app={app} group={g}/>{g.total>20&&<div className="button-pair"><Button variant="ghost" disabled={g.order_offset===0} onClick={()=>{setGroup(g.group_id);setOffset(0);setOrderOffset(Math.max(0,g.order_offset-20));}}>上一页订单</Button><span>{g.order_offset+1}–{Math.min(g.total,g.order_offset+20)} / {g.total}</span><Button variant="ghost" disabled={g.order_offset+20>=g.total} onClick={()=>{setGroup(g.group_id);setOffset(0);setOrderOffset(g.order_offset+20);}}>下一页订单</Button></div>}</section>)}</div>
    {!!data&&data.total>20&&<div className="button-pair"><Button variant="ghost" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-20))}>上一页客户</Button><span>{offset+1}–{Math.min(data.total,offset+20)} / {data.total}</span><Button variant="ghost" disabled={offset+20>=data.total} onClick={()=>setOffset(offset+20)}>下一页客户</Button></div>}
  </section>;
}
