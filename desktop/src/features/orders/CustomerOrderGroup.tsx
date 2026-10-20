import { useId } from "react";
import type { CustomerGroup } from "../../contracts";
import type { Workbench } from "../../state/useWorkbench";
import { money } from "../../state/format";
import { Button } from "../../ui/components";
import { CustomerIdentity } from "./CustomerIdentity";
import { CustomerOrderTable } from "./CustomerOrderTable";

export function CustomerOrderGroup({app, group, onPage}: {app: Workbench; group: CustomerGroup; onPage: (offset: number) => void}) {
  const heading = useId();
  return <section className="customer-group" aria-labelledby={heading}>
    <header className="customer-group-header">
      <div id={heading}><CustomerIdentity details={group.details} heading/></div>
      <div className="customer-group-summary">
        <span>共 {group.total} 笔订单 · 有效 {group.active_count} 笔</span>
        <span>有效订单合计 <strong className="numeric">¥{money(group.totals.income_cents)}</strong></span>
      </div>
      <Button variant="outline" disabled={app.busy || app.pending} onClick={() => app.chooseCustomer(group, true)}>{app.draft.editing ? "关联到该客户" : "该客户新建订单"}</Button>
    </header>
    <CustomerOrderTable app={app} group={group}/>
    {group.total > 20 && <footer className="customer-order-pagination button-pair">
      <Button variant="ghost" disabled={app.busy || group.order_offset === 0} onClick={() => onPage(Math.max(0, group.order_offset - 20))}>上一页订单</Button>
      <span>{group.order_offset + 1}–{Math.min(group.total, group.order_offset + 20)} / {group.total}</span>
      <Button variant="ghost" disabled={app.busy || group.order_offset + 20 >= group.total} onClick={() => onPage(group.order_offset + 20)}>下一页订单</Button>
    </footer>}
  </section>;
}
