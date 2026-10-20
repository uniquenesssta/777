import { useState } from "react";
import type { Workbench } from "../state/useWorkbench";
import { useCustomers } from "../state/useCustomers";
import { Button, Empty, Input } from "../ui/components";
import { CustomerOrderGroup } from "./orders/CustomerOrderGroup";
import "./orders/orderRecords.css";

export function CustomerOrders({app, onAll}: {app: Workbench; onAll: () => void}) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [group, setGroup] = useState<string>();
  const [orderOffset, setOrderOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const {data, error, loading} = useCustomers(app, query, offset, group, orderOffset, !!app.session, refresh);
  return <section className="card orders-card" data-node-id="84:1646">
    <div className="section-heading">
      <h2>{app.navigationRole === "admin" ? "订单记录" : "我的订单"}</h2>
      <div className="button-pair"><Button variant="ghost" onClick={onAll}>全部订单</Button><Button aria-pressed>按客户查看</Button></div>
    </div>
    <form className="order-filters" onSubmit={event => {
      event.preventDefault(); setQuery(input); setOffset(0); setGroup(undefined); setOrderOffset(0); setRefresh(value => value + 1);
    }}>
      <Input aria-label="搜索客户" placeholder="客户 / 淘宝 ID、微信号或订单号" value={input} maxLength={256} onChange={event => setInput(event.target.value)}/>
      <Button type="submit" disabled={app.busy || loading}>查找</Button>
      {group && <Button variant="ghost" onClick={() => {setGroup(undefined); setOrderOffset(0);}}>返回客户列表</Button>}
    </form>
    {loading && <p>读取客户订单…</p>}{error && <p role="alert">{error}</p>}
    {data?.total === 0 && <Empty>暂无匹配的客户订单。</Empty>}
    <div className="customer-groups">{data?.groups.map(customer => <CustomerOrderGroup key={customer.group_id} app={app} group={customer} onPage={next => {
      setGroup(customer.group_id); setOffset(0); setOrderOffset(next);
    }}/>)}</div>
    {!!data && data.total > 20 && <div className="button-pair">
      <Button variant="ghost" disabled={app.busy || loading || !offset} onClick={() => setOffset(Math.max(0, offset - 20))}>上一页客户</Button>
      <span>{offset + 1}–{Math.min(data.total, offset + 20)} / {data.total}</span>
      <Button variant="ghost" disabled={app.busy || loading || offset + 20 >= data.total} onClick={() => setOffset(offset + 20)}>下一页客户</Button>
    </div>}
  </section>;
}
