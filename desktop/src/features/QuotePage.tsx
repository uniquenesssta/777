import { useEffect, useState } from "react";
import type { Line, Money, Order, RawLine } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { snapshot } from "../state/draft";
import { money } from "../state/format";
import { Button, Field, Icon, Input, Modal } from "../ui/components";
export function Summary({
  amounts,
  lines,
  admin,
  children,
  submitted = false,
}: {
  amounts: Money | null;
  lines: Line[];
  admin: boolean;
  children: React.ReactNode;
  submitted?: boolean;
}) {
  const normal = lines.filter((l) => l.raw.line_kind === "normal");
  const discounts = lines.filter((l) => l.raw.line_kind === "discount");
  const total = (a: Line[]) =>
    a.reduce((v, l) => v + BigInt(l.income_cents), 0n).toString();
  return (
    <aside className="card settlement" data-admin={admin}>
      <section className="amount-card">
        <div className="amount-label">
          <span>{submitted ? "订单金额" : "应收合计"}</span>
          <small>CNY</small>
        </div>
        <div className="amount">
          <span>¥</span>
          <strong>{money(amounts?.income_cents)}</strong>
        </div>
        <small>
          {amounts ? `已计入 ${discounts.length} 条折扣` : "请计算并核对报价"}
        </small>
      </section>
      <div className="breakdown">
        <div>
          <span>商品小计</span>
          <b>{amounts ? money(total(normal)) : "—"}</b>
        </div>
        <div>
          <span>顺序折扣</span>
          <b className="accent">{amounts ? money(total(discounts)) : "—"}</b>
        </div>
      </div>
      {admin && (
        <section className="finance">
          <small className="muted">
            <Icon name="lock" />
            仅管理员可见
          </small>
          <div className="finance-cost">
            <span>商品成本</span>
            <b>{money(amounts?.cost_cents)}</b>
          </div>
          <div className="profit-pair">
            <div>
              <small>预计利润</small>
              <strong>{money(amounts?.profit_cents)}</strong>
            </div>
            <div>
              <small>利润率</small>
              <strong>{amounts?.financial_display?.margin ?? "—"}</strong>
            </div>
          </div>
        </section>
      )}
      <div className="settlement-actions">{children}</div>
    </aside>
  );
}
export function QuotePage({ app }: { app: Workbench }) {
  const [confirm, setConfirm] = useState(false);
  const [confirmRevision, setConfirmRevision] = useState("");
  const [adding, setAdding] = useState(false);
  const [product, setProduct] = useState("");
  const { draft, catalog, dispatch } = app;
  const result = draft.calculation;
  const valid =
    result?.status === "ok" &&
    draft.calculatedRevision === draft.revision &&
    !app.pending;
  useEffect(() => {
    if (confirm && confirmRevision !== draft.revision) setConfirm(false);
  }, [draft.revision, confirmRevision, confirm]);
  const editLine = (id: string, field: string, value: string) =>
    dispatch({
      type: "edit",
      lines: draft.lines.map((l) =>
        l.id === id
          ? { ...l, raw: { ...l.raw, [field]: value } as RawLine }
          : l,
      ),
    });
  const remove = (id: string) =>
    dispatch({ type: "edit", lines: draft.lines.filter((l) => l.id !== id) });
  const add = () => {
    const item = catalog?.items.find((p) => p.product_id === product);
    if (!item) return;
    dispatch({
      type: "edit",
      lines: [
        ...draft.lines,
        {
          id: crypto.randomUUID(),
          raw: {
            line_kind: "normal",
            product_id: item.product_id,
            q: "1",
            h: "",
            w: "",
            name: "",
          },
        },
      ],
    });
    setAdding(false);
  };
  return (
    <>
      <div
        className="workbench-grid"
        data-node-id={app.session?.role === "admin" ? "21:3" : "40:1604"}
      >
        <section className="card quote-card">
          <div className="customer-row">
            {(["customer", "order_ref", "wechat"] as const).map((k, i) => (
              <Field
                compact
                label={["客户 / 淘宝 ID", "订单号", "微信号"][i]}
                key={k}
              >
                <Input
                  maxLength={4096}
                  value={draft.details[k]}
                  onChange={(e) =>
                    dispatch({
                      type: "edit",
                      details: { ...draft.details, [k]: e.target.value },
                    })
                  }
                />
              </Field>
            ))}
          </div>
          <div className="section-heading">
            <h2>
              商品明细{" "}
              <small>
                {draft.lines.filter((l) => l.raw.line_kind === "normal").length}{" "}
                个项目
              </small>
            </h2>
            <Button
              variant="ghost"
              className="price-version"
              onClick={() => void app.refreshPrices()}
              disabled={app.busy}
            >
              <Icon name="check" />
              价格版本 {catalog?.price_version_id.slice(0, 16) ?? "未连接"}
            </Button>
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
              {draft.lines.map((l, index) => {
                const raw = l.raw;
                const calculated = result?.lines[index];
                if (raw.line_kind === "discount")
                  return (
                    <div className="discount-row" key={l.id}>
                      <b>折</b>
                      <span>顺序折扣</span>
                      <Input
                        aria-label={`第${index + 1}行折扣`}
                        className="cell-input discount-input"
                        value={raw.percent}
                        onChange={(e) =>
                          editLine(l.id, "percent", e.target.value)
                        }
                      />
                      <small>对以上商品小计打折</small>
                      <strong>{money(calculated?.income_cents)}</strong>
                      <Button
                        variant="ghost"
                        aria-label={`删除第${index + 1}行`}
                        onClick={() => remove(l.id)}
                      >
                        <Icon name="discount-trash" />
                      </Button>
                    </div>
                  );
                const price = catalog?.items.find(
                  (p) => p.product_id === raw.product_id,
                );
                return (
                  <div className="quote-row" key={l.id}>
                    <small className="row-number">
                      {String(index + 1).padStart(2, "0")}
                    </small>
                    <div className="product-cell">
                      <b>{raw.product_id}</b>
                      <small>{price?.single ? "单件计价" : "面积计价"}</small>
                    </div>
                    <div className="dimensions">
                      {price?.single ? (
                        <small className="faint">无需填写尺寸</small>
                      ) : (
                        <>
                          <Input
                            aria-label={`第${index + 1}行高`}
                            className="cell-input"
                            value={raw.h}
                            onChange={(e) =>
                              editLine(l.id, "h", e.target.value)
                            }
                          />
                          <span>×</span>
                          <Input
                            aria-label={`第${index + 1}行宽`}
                            className="cell-input"
                            value={raw.w}
                            onChange={(e) =>
                              editLine(l.id, "w", e.target.value)
                            }
                          />
                        </>
                      )}
                    </div>
                    <Input
                      aria-label={`第${index + 1}行数量`}
                      className="cell-input quantity"
                      value={raw.q}
                      onChange={(e) => editLine(l.id, "q", e.target.value)}
                    />
                    <span className="cell-value">{price?.sale ?? "—"}</span>
                    <span className="cell-value">{price?.k || "1"}</span>
                    <strong className="line-amount">
                      {money(calculated?.income_cents)}
                    </strong>
                    <Button
                      variant="ghost"
                      aria-label={`删除第${index + 1}行`}
                      onClick={() => remove(l.id)}
                    >
                      <Icon name="trash" />
                    </Button>
                  </div>
                );
              })}
            </div>
            {draft.lines.length === 0 && (
              <p className="empty">添加商品，开始录入报价。</p>
            )}
          </div>
          <div className="add-actions">
            <Button
              variant="outline"
              onClick={() => {
                setProduct(catalog?.items[0]?.product_id ?? "");
                setAdding(true);
              }}
              disabled={!catalog || draft.lines.length >= 1000}
            >
              ＋ 添加商品
            </Button>
            <Button
              variant="ghost"
              onClick={() =>
                dispatch({
                  type: "edit",
                  lines: [
                    ...draft.lines,
                    {
                      id: crypto.randomUUID(),
                      raw: { line_kind: "discount", percent: "95%", name: "" },
                    },
                  ],
                })
              }
              disabled={!catalog || draft.lines.length >= 1000}
            >
              ＋ 添加折扣
            </Button>
          </div>
          {result?.status !== "ok" &&
            result?.issues.map((e, i) => (
              <div className="inline-error" key={i}>
                第{e.line_index === null ? "—" : e.line_index + 1}行 · {e.field}
                ：{e.reason}
              </div>
            ))}
          <footer className="entry-hints">
            <span>金额按行计算，折扣按顺序依次生效。</span>
            <small>面积单位 m² · 金额单位 ¥</small>
          </footer>
        </section>
        <Summary
          amounts={result?.totals ?? null}
          lines={result?.lines ?? []}
          admin={app.session?.role === "admin"}
        >
          <Button
            disabled={
              app.busy || !catalog || !draft.lines.length || app.pending
            }
            onClick={() => {
              if (valid) {
                setConfirmRevision(draft.revision);
                setConfirm(true);
              } else void app.calculate();
            }}
          >
            {app.busy ? "处理中…" : valid ? "核对并提交订单" : "计算报价"}
          </Button>
          <p>提交前再次核对价格与商品信息。</p>
          {!valid && draft.lines.length > 0 && (
            <small>输入修改后需重新计算。</small>
          )}
        </Summary>
      </div>
      <Modal
        open={confirm}
        onOpenChange={(v) => !app.busy && setConfirm(v)}
        title="确认提交订单"
        description={`${draft.details.customer || "未填写客户"} · ${draft.details.order_ref || "未填写订单号"}`}
        compact
      >
        <div className="confirm-amount">
          <span>应收合计</span>
          <strong>¥ {money(result?.totals?.income_cents)}</strong>
        </div>
        <div className="dialog-actions">
          <Button
            variant="outline"
            disabled={app.busy}
            onClick={() => setConfirm(false)}
          >
            返回修改
          </Button>
          <Button
            disabled={app.busy || !valid}
            onClick={async () => {
              setConfirm(false);
              await app.submit();
            }}
          >
            确认提交
          </Button>
        </div>
      </Modal>
      <Modal
        open={adding}
        onOpenChange={setAdding}
        title="添加商品"
        description="选择已发布的商品价格。"
      >
        <Field label="商品">
          <select
            aria-label="商品"
            value={product}
            onChange={(e) => setProduct(e.target.value)}
          >
            {catalog?.items.map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.product_id}
              </option>
            ))}
          </select>
        </Field>
        <div className="dialog-actions">
          <Button variant="outline" onClick={() => setAdding(false)}>
            取消
          </Button>
          <Button onClick={add} disabled={!product}>
            添加
          </Button>
        </div>
      </Modal>
    </>
  );
}
