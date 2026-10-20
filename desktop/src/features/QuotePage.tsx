import { SubmitRecovery } from "./SubmitRecovery";
import { CustomerMatches } from "./CustomerMatches";
import { useEffect, useRef, useState } from "react";
import type { Line, Money, Order, RawLine } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { useLineReorder } from "./useLineReorder";
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
          <span>折扣合计</span>
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
  const { draft, catalog, dispatch } = app;
  const reorder = useLineReorder(draft.lines, lines => dispatch({type:"edit", lines}), app.busy || app.pending);
  const addedLine = useRef<string | null>(null);
  useEffect(() => {
    const id = addedLine.current;
    if (!id) return;
    const row = document.getElementById(`quote-line-${id}`);
    if (!row) return;
    addedLine.current = null;
    row.scrollIntoView({ block: "nearest", inline: "nearest" });
    row.querySelector<HTMLSelectElement>("select")?.focus({ preventScroll: true });
  }, [draft.lines]);
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
    const item = catalog?.items[0];
    if (!item) return;
    const id = crypto.randomUUID();
    addedLine.current = id;
    dispatch({
      type: "edit",
      lines: [
        ...draft.lines,
        {
          id,
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
  };
  return (
    <>
      <div
        className="workbench-grid"
        data-node-id={app.can("finance") ? "21:3" : "40:1604"}
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
                  maxLength={256}
                  value={draft.details[k]}
                  onChange={(e) => {
                    dispatch({
                      type: "edit",
                      details: { ...draft.details, [k]: e.target.value },
                    });}
                  }
                />
              </Field>
            ))}
          </div>
          {draft.editing ? <div className="customer-match editing-context"><strong>编辑订单 {draft.details.order_ref || "未填写订单号"}</strong><span>已保存版本 {draft.editing.revision}</span><Button variant="ghost" onClick={()=>void app.readOrder(draft.editing!.order_id)}>查看修改记录</Button></div> : null}
          {app.can("orders") && <CustomerMatches app={app} />}
          <div className="section-heading">
            <h2>
              商品明细{" "}
              <small>
                {draft.lines.filter((l) => l.raw.line_kind === "normal").length}{" "}
                个项目
              </small>
            </h2>
            <div className="section-actions">
            <Button variant="outline" disabled={app.working || app.pending} onClick={app.clearQuote}>一键清除</Button>
            <Button
              variant="ghost"
              className="price-version"
              onClick={() => void app.refreshPrices()}
              disabled={app.busy}
            >
              <Icon name="check" />
              {app.formal ? "刷新价格" : `价格版本 ${catalog?.price_version_id.slice(0, 16) ?? "未连接"}`}
            </Button></div>
          </div>
          <div className="line-scroll" tabIndex={0} role="region" aria-label="商品明细滚动区">
            <div className="quote-table quote-entry-table">
              <div className="quote-row table-head">
                <span />
                <span>商品 / 计价方式</span>
                <span className="head-dimensions">高 × 宽（m）</span>
                <span className="head-number">数量</span>
                <span className="head-amount">金额（¥）</span>
                <span />
              </div>
              {draft.lines.map((l, index) => {
                const raw = l.raw;
                const calculated = result?.lines[index];
                if (raw.line_kind === "discount")
                  return (
                    <div className="discount-row" key={l.id} id={`quote-line-${l.id}`} {...reorder.row(l.id,index)}>
                      {reorder.handle(l.id,index)}
                      <b>折</b>
                      <Input
                        aria-label={`第${index + 1}行折扣`}
                        className="cell-input discount-input"
                        value={raw.percent}
                        onChange={(e) =>
                          editLine(l.id, "percent", e.target.value)
                        }
                      />
                      <small>对上方参与折扣的商品打折</small>
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
                const current = catalog?.items.find((p) => p.product_id === raw.product_id);
                const frozen=l.frozen?.product_id===raw.product_id?l.frozen:undefined;
                const price=frozen?{...current,...frozen,unit_sale:frozen.sale,pricing_mode:undefined}:current;
                return (
                  <div className="quote-row" key={l.id} id={`quote-line-${l.id}`} {...reorder.row(l.id,index)}>
                    {reorder.handle(l.id,index)}
                    <div className="product-cell">
                      <select className="product-select" aria-label={`第${index + 1}行商品`} value={raw.product_id} onChange={e => editLine(l.id, "product_id", e.target.value)} disabled={!catalog}>
                        {!current && <option value={raw.product_id}>{raw.product_id}（已下架）</option>}
                        {catalog?.items.map(p => <option key={p.product_id} value={p.product_id}>{p.product_id}</option>)}
                      </select>
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
              onClick={add}
              disabled={!catalog?.items.length || draft.lines.length >= 1000}
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
              disabled={!catalog?.items.length || draft.lines.length >= 1000}
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
            <span>拖动左侧调整顺序，折扣仅影响上方参与折扣的商品。</span>
            {reorder.announcement && <span className="sr-only" role="status">{reorder.announcement}</span>}
            <small>面积单位 m² · 金额单位 ¥</small>
          </footer>
        </section>
        <Summary
          amounts={result?.totals ?? null}
          lines={result?.lines ?? []}
          admin={app.can("finance")}
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
            {app.working ? "处理中…" : valid ? (app.saveFailure ? "再次提交" : draft.editing?"保存修改":"核对并提交订单") : app.saveFailure ? "重新核价" : "计算报价"}
          </Button>
          {valid && app.saveFailure && <Button variant="outline" disabled={app.busy || app.pending} onClick={() => void app.calculate()}>重新核价</Button>}
          {draft.editing && <Button variant="ghost" disabled={app.busy||app.pending} onClick={app.cancelEdit}>取消编辑</Button>}
          {app.pending && !app.formal && (
            <section className="pending-actions" aria-label="原请求处理">
              <p>{!app.isError && app.feedback ? app.feedback : "原请求结果待核查。"}</p>
              <Button variant="outline" disabled={app.busy} onClick={() => void app.recover(false)}>
                核查原请求
              </Button>
              <Button variant="outline" disabled={app.busy} onClick={() => void app.recover(true)}>
                按原请求重试
              </Button>
            </section>
          )}
          {!valid && draft.lines.length > 0 && (
            <small>输入修改后需重新计算。</small>
          )}
        </Summary>
      </div>
      <SubmitRecovery app={app} valid={!!valid} />
      <Modal
        open={confirm}
        onOpenChange={(v) => !app.busy && setConfirm(v)}
        title={draft.editing?"确认保存修改":"确认提交订单"}
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

    </>
  );
}
