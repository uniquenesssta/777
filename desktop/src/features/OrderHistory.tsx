import { useEffect, useState } from "react";
import type { Order, OrderChanges } from "../contracts";
import { request, errorMessage } from "../bridge";
import { money, stamp } from "../state/format";
import { Button } from "../ui/components";
function Revision({ orderId, history }: {orderId:string;history:NonNullable<Order["history"]>[number]}) {
  const [open,setOpen]=useState(false),[value,setValue]=useState<OrderChanges|null>(null),[error,setError]=useState("");
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    if(!open||value)return;
    let active=true;setError("");
    request<OrderChanges>("order_changes",{order_id:orderId,revision:history.revision}).then(v=>{if(active)setValue(v);},e=>{if(active)setError(errorMessage(e));});
    return ()=>{active=false;};
  },[open,value,orderId,history.revision,attempt]);
  const rendered=(v:string|null,format:string)=>v===null||v===""?"—":format==="money"?`¥${money(v)}`:v;
  return <details className="revision-diff" onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>版本 {history.revision} → {String(BigInt(history.revision)+1n)} <small>· {stamp(history.created_at)}</small></summary>
    {open&&<>
      {error?<p role="alert">{error} <Button variant="ghost" onClick={()=>setAttempt(n=>n+1)}>重试读取</Button></p>:!value?<p role="status">正在读取修改记录…</p>:<>
        <p className="muted">商品按明细位置对照；金额为该次保存前后的值。</p>
        {value.changes.length?<div className="orders-table-scroll"><table className="orders-table diff-table"><thead><tr><th>修改项目</th><th>修改前</th><th>修改后</th></tr></thead><tbody>{value.changes.map((c,i)=><tr key={i}><td>{c.section} · {c.field}</td><td>{rendered(c.before,c.format)}</td><td>{rendered(c.after,c.format)}</td></tr>)}</tbody></table></div>:<p className="muted">本次保存未改变客户信息、商品明细或金额。</p>}
      </>}
    </>}
  </details>;
}
export function OrderHistory({order}:{order:Order}) {
  if(!order.history?.length)return null;
  return <section className="note-history order-history"><h3>修改记录</h3>{order.history.map(h=><Revision key={`${order.order_id}:${h.revision}`} orderId={order.order_id} history={h}/>)}</section>;
}
