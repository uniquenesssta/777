import { useState } from "react";
import type { Workbench } from "../state/useWorkbench";
import { money, stamp } from "../state/format";
import { Summary } from "./QuotePage";
import { Badge, Button, Empty, Modal } from "../ui/components";
export function DetailPage({ app }: { app: Workbench }) {
  const [dialog, setDialog] = useState<"note" | "state" | null>(null);
  const [text, setText] = useState("");
  const order = app.selected;
  if (!order) return <Empty>请选择一笔订单。</Empty>;
  return (
    <>
      <div className="workbench-grid" data-node-id="32:499">
        <section className="card quote-card">
          <div className="customer-row readonly-customer">
            <div>
              <small>客户 / 淘宝 ID</small>
              <span>{order.details.customer || "—"}</span>
            </div>
            <div>
              <small>订单号</small>
              <span>{order.details.order_ref || "—"}</span>
            </div>
            <div>
              <small>微信号</small>
              <span>{order.details.wechat || "—"}</span>
            </div>
          </div>
          <div className="section-heading">
            <h2>商品明细</h2>
            <div className="detail-status">
              <Badge muted={order.state === "void"}>
                {order.state === "active" ? "已保存" : "已作废"}
              </Badge>
              <small>{stamp(order.created_at)}</small>
            </div>
          </div>
          <div className="line-scroll">
            <div className="quote-table">
              <div className="quote-row table-head">
                <span />
                <span>商品 / 计价方式</span>
                <span>高 × 宽（m）</span>
                <span>数量</span>
                <span>单价（¥）</span>
                <span>K</span>
                <span className="right">金额（¥）</span>
                <span />
              </div>
              {order.lines.map((line, index) =>
                line.raw.line_kind === "discount" ? (
                  <div className="discount-row" key={index}>
                    <b>折</b>
                    <span>顺序折扣</span>
                    <span>{line.raw.percent}</span>
                    <small>对以上商品小计打折</small>
                    <strong>{money(line.income_cents)}</strong>
                  </div>
                ) : (
                  <div className="quote-row" key={index}>
                    <small className="row-number">
                      {String(index + 1).padStart(2, "0")}
                    </small>
                    <div className="product-cell">
                      <b>{line.raw.product_id}</b>
                      <small>
                        {line.normalized.h && line.normalized.w
                          ? "面积计价"
                          : "单件计价"}
                      </small>
                    </div>
                    <span>
                      {line.normalized.h && line.normalized.w
                        ? `${line.normalized.h} × ${line.normalized.w}`
                        : "—"}
                    </span>
                    <span>{line.normalized.q}</span>
                    <span>{line.normalized.sale}</span>
                    <span>{line.normalized.k}</span>
                    <strong className="line-amount">
                      {money(line.income_cents)}
                    </strong>
                    <span />
                  </div>
                ),
              )}
            </div>
          </div>
          <section className="note-history">
            <h3>备注记录</h3>
            {order.notes.length ? (
              order.notes.map((n) => (
                <div key={n.note_id}>
                  <p>{n.body}</p>
                  <small>{stamp(n.created_at)}</small>
                </div>
              ))
            ) : (
              <p className="muted">暂无备注</p>
            )}
          </section>
        </section>
        <Summary
          amounts={order}
          lines={order.lines}
          admin={app.session?.role === "admin"}
          submitted
        >
          <Button disabled={app.busy} onClick={() => app.navigate("orders")}>
            返回订单记录
          </Button>
          <div className="button-pair">
            <Button
              variant="outline"
              disabled={app.busy || app.pending}
              onClick={() => {
                setText("");
                setDialog("note");
              }}
            >
              追加备注
            </Button>
            {app.session?.role === "admin" && (
              <Button
                variant="outline"
                disabled={app.busy || app.pending}
                onClick={() => {
                  setText("");
                  setDialog("state");
                }}
              >
                {order.state === "active" ? "作废订单" : "恢复订单"}
              </Button>
            )}
          </div>
          <div className="button-pair">
            <Button
              variant="ghost"
              disabled={app.busy || app.pending}
              onClick={() => app.output("excel_quote")}
            >
              导出报价
            </Button>
            <Button
              variant="ghost"
              disabled={app.busy || app.pending}
              onClick={() => app.output("quote_png")}
            >
              报价图片
            </Button>
          </div>
          {app.session?.role === "admin" && (
            <Button
              variant="ghost"
              disabled={app.busy || app.pending}
              onClick={() => app.output("excel_admin")}
            >
              内部财务报表
            </Button>
          )}
        </Summary>
      </div>
      <Modal
        open={!!dialog}
        onOpenChange={(v) => !v && !app.busy && setDialog(null)}
        title={
          dialog === "note"
            ? "追加备注"
            : order.state === "active"
              ? "作废订单"
              : "恢复订单"
        }
        description={
          dialog === "note"
            ? "备注仅追加，原记录会一直保留。"
            : "请填写原因，原订单金额和备注会保留。"
        }
      >
        <textarea
          aria-label={dialog === "note" ? "备注内容" : "操作原因"}
          value={text}
          maxLength={4096}
          rows={3}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="dialog-actions">
          <Button
            variant="outline"
            disabled={app.busy}
            onClick={() => setDialog(null)}
          >
            取消
          </Button>
          <Button
            disabled={app.busy || !text.trim() || app.pending}
            onClick={async () => {
              const saved =
                dialog === "note"
                  ? await app.note(text)
                  : await app.changeState(text);
              if (saved) setDialog(null);
            }}
          >
            确认
          </Button>
        </div>
      </Modal>
    </>
  );
}
