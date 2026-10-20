import type { CustomerGroup } from "../../contracts";
import type { Workbench } from "../../state/useWorkbench";
import { money, stamp } from "../../state/format";
import { Badge, Button } from "../../ui/components";

export function CustomerOrderTable({app, group}: {app: Workbench; group: CustomerGroup}) {
  return <div className="customer-orders-scroll" tabIndex={0} role="region" aria-label="客户订单滚动区">
    <table className="orders-table order-records-table customer-orders-table" aria-label="客户订单">
      <thead><tr><th scope="col">订单号</th><th scope="col">创建时间</th><th scope="col" className="right">应收金额（¥）</th><th scope="col">状态</th><th scope="col" className="order-action-column">操作</th></tr></thead>
      <tbody>{group.orders.map(order => <tr key={order.order_id}>
        <td className="order-reference">{order.details.order_ref || "未填写订单号"}</td>
        <td>{stamp(order.created_at)}</td>
        <td className="right numeric">{money(order.income_cents)}</td>
        <td><Badge muted={order.state === "void"}>{order.state === "active" ? "已保存" : "已作废"}</Badge></td>
        <td><div className="order-row-actions">
          <Button variant="ghost" disabled={app.busy || app.pending} onClick={() => void app.readOrder(order.order_id)}>查看</Button>
          {app.can("edit_orders") && order.state === "active" && <Button variant="ghost" disabled={app.busy || app.pending} onClick={() => void app.beginEdit(order.order_id)}>继续编辑</Button>}
        </div></td>
      </tr>)}</tbody>
    </table>
  </div>;
}
