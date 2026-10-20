import { CustomerOrders } from "./CustomerOrders";
import { useState, useRef, useLayoutEffect } from "react";
import type { Workbench } from "../state/useWorkbench";
import { money, stamp } from "../state/format";
import { Badge, Button, Empty, Input } from "../ui/components";
export function OrdersPage({
  app,
}: {
  app: Workbench;
}) {
  const [customerMode,setCustomerMode]=useState(false);
  const [q, setQ] = useState(app.filters.q);
  const [state, setState] = useState(app.filters.state);
  const page = app.listing;
  const scroll = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (scroll.current) scroll.current.scrollTop = app.listScrollRef.current;
  }, [app.listing]);
  if(customerMode)return <CustomerOrders app={app} onAll={()=>setCustomerMode(false)}/>;
  return (
    <section className="card orders-card" data-node-id="32:96">
      <div className="section-heading">
        <h2>
          {app.navigationRole === "admin" ? "订单记录" : "我的订单"}{" "}
          <small>{page?.total ?? 0} 条</small>
        </h2>
        <div className="section-actions"><Button variant="outline" onClick={()=>setCustomerMode(true)}>按客户查看</Button>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.loadOrders({ ...app.filters, view: "" })}
        >
          刷新
        </Button></div>
      </div>
      <form
        className="order-filters"
        onSubmit={(e) => {
          e.preventDefault();
          void app.loadOrders({ q, state, offset: 0, view: "" });
        }}
      >
        <Input
          aria-label="搜索订单"
          placeholder="搜索订单号、客户或微信"
          value={q}
          maxLength={256}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          aria-label="订单状态"
          value={state}
          onChange={(e) => setState(e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="active">已保存</option>
          <option value="void">已作废</option>
        </select>
        <Button type="submit" disabled={app.busy}>
          筛选
        </Button>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => {
            setQ("");
            setState("");
            void app.loadOrders({ q: "", state: "", offset: 0, view: "" });
          }}
        >
          重置
        </Button>
      </form>
      <div
        className="orders-table-scroll"
        tabIndex={0}
        role="region"
        aria-label="订单列表滚动区"
        ref={scroll}
        onScroll={(e) => {
          app.listScrollRef.current = e.currentTarget.scrollTop;
        }}
      >
        <table className="orders-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>客户 / 淘宝 ID</th>
              <th className="right">应收金额（¥）</th>
              {app.can("finance") && (
                <th className="right">利润（¥）</th>
              )}
              <th>创建时间</th>
              <th>创建人</th>
              <th>状态</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {page?.orders.map((o) => (
              <tr
                key={o.order_id}
                data-selected={app.selected?.order_id === o.order_id}
              >
                <td>{o.details.order_ref || "—"}</td>
                <td>{o.details.customer || "—"}</td>
                <td className="right numeric">{money(o.income_cents)}</td>
                {app.can("finance") && (
                  <td className="right numeric">{money(o.profit_cents)}</td>
                )}
                <td>{stamp(o.created_at)}</td>
                <td>{o.owner_id?.slice(0, 8) || app.session?.username}</td>
                <td>
                  <Badge muted={o.state === "void"}>
                    {o.state === "active" ? "已保存" : "已作废"}
                  </Badge>
                </td>
                <td>
                  <Button
                    variant="ghost"
                    disabled={app.busy}
                    onClick={() => void app.readOrder(o.order_id)}
                  >
                    查看详情
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!page?.orders.length && (
          <Empty>{app.working ? "正在读取订单…" : !app.session ? "" : "没有符合条件的订单。"}</Empty>
        )}
      </div>
      <footer className="pagination">
        <small>共 {page?.total ?? 0} 条 · 每页 20 条</small>
        <div>
          <Button
            variant="ghost"
            aria-label="上一页"
            disabled={app.busy || !page || page.offset === 0}
            onClick={() =>
              void app.loadOrders({
                ...app.filters,
                offset: Math.max(0, (page?.offset ?? 0) - 20),
                view: page?.view ?? "",
              })
            }
          >
            ‹
          </Button>
          <span>
            {Math.floor((page?.offset ?? 0) / 20) + 1} /{" "}
            {Math.max(1, Math.ceil((page?.total ?? 0) / 20))}
          </span>
          <Button
            variant="ghost"
            aria-label="下一页"
            disabled={app.busy || !page || page.offset + 20 >= page.total}
            onClick={() =>
              void app.loadOrders({
                ...app.filters,
                offset: (page?.offset ?? 0) + 20,
                view: page?.view ?? "",
              })
            }
          >
            ›
          </Button>
        </div>
      </footer>
    </section>
  );
}
