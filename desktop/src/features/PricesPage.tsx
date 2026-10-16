import { useEffect, useRef, useState } from "react";
import type { Price } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { request } from "../bridge";
import { Badge, Button, Icon, Input, Modal } from "../ui/components";
import "./prices.css";

type Row = Price & { id: string; source?: Price; changed: boolean };
type Preview = { key: string; sale?: string; error?: string };
const previewKey = (p: Price) => JSON.stringify([p.cost ?? "", p.k]);
const wire = (p: Price): Price => ({
  product_id: p.product_id,
  sale: p.pricing_mode === "cost_plus" ? "" : p.sale,
  cost: p.cost,
  k: p.k,
  single: p.single,
  ...(p.pricing_mode ? { pricing_mode: p.pricing_mode } : {}),
});
export function PricesPage({ app }: { app: Workbench }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const [confirm, setConfirm] = useState(false);
  const [focusRow, setFocusRow] = useState<string | null>(null);
  const newProduct = useRef<HTMLInputElement>(null);
  const supported = (app.catalog?.pricing_mode_version ?? app.session?.pricing_mode_version) === "final-unit-v1";
  useEffect(() => {
    if (!focusRow) return;
    newProduct.current?.focus();
    newProduct.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
    setFocusRow(null);
  }, [focusRow]);
  useEffect(() => {
    const rows = (app.catalog?.items ?? []).map((p) => ({
      ...p,
      id: crypto.randomUUID(),
      sale: p.unit_sale ?? p.sale,
      pricing_mode: p.pricing_mode ?? ("manual" as const),
      source: p,
      changed: false,
    }));
    setRows(rows);
    setPreviews(
      Object.fromEntries(
        rows
          .filter(
            (p) => p.pricing_mode === "cost_plus" && p.unit_sale !== undefined,
          )
          .map((p) => [p.id, { key: previewKey(p), sale: p.unit_sale }]),
      ),
    );
  }, [app.catalog]);
  const signature = JSON.stringify(
    rows
      .filter((p) => p.pricing_mode === "cost_plus")
      .map((p) => [p.id, previewKey(p)]),
  );
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      for (const p of rows.filter(
        (p) =>
          p.pricing_mode === "cost_plus" &&
          previews[p.id]?.key !== previewKey(p),
      )) {
        const key = previewKey(p);
        void request<{ sale: string }>("price_preview", {
          cost: p.cost ?? "",
          k: p.k,
        }).then(
          (result) => {
            if (!cancelled)
              setPreviews((old) => ({
                ...old,
                [p.id]: { key, sale: result.sale },
              }));
          },
          () => {
            if (!cancelled)
              setPreviews((old) => ({
                ...old,
                [p.id]: { key, error: "请检查成本单价与K。" },
              }));
          },
        );
      }
    }, 120);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [signature]);
  const edit = (id: string, change: Partial<Price>) =>
    setRows((old) =>
      old.map((p) => (p.id === id ? { ...p, ...change, changed: true } : p)),
    );
  const ready =
    supported &&
    rows.length > 0 &&
    rows.every(
      (p) =>
        p.product_id.trim() !== "" &&
        (p.pricing_mode === "cost_plus"
          ? previews[p.id]?.key === previewKey(p) &&
            previews[p.id]?.sale !== undefined
          : p.sale.trim() !== ""),
    );
  return (
    <section className="price-maintenance" aria-labelledby="price-title">
      <div className="price-toolbar">
        <div className="price-title">
          <h2 id="price-title">价格维护</h2>
          <Badge muted>{rows.length} 种商品</Badge>
        </div>
        <div className="price-toolbar-actions">
          <Button
            variant="ghost"
            disabled={app.busy}
            onClick={() => void app.refreshPrices()}
          >
            重新读取
          </Button>
          <Button
            variant="outline"
            disabled={app.busy || !supported || rows.length >= 1000}
            onClick={() => {
              const id = crypto.randomUUID();
              setRows((old) => [
                ...old,
                {
                  id,
                  product_id: "",
                  sale: "",
                  cost: "",
                  k: "1",
                  single: false,
                  pricing_mode: "manual",
                  changed: true,
                },
              ]);
              setFocusRow(id);
            }}
          >
            ＋ 添加商品
          </Button>
        </div>
      </div>
      {!supported && (
        <p className="inline-error">
          当前服务不支持新的定价方式，请更新服务后重新读取。
        </p>
      )}
      <div className="card price-catalog">
        <div className="price-table-scroll" role="region" aria-label="价格目录" tabIndex={0}>
          <table className="price-editor">
            <caption className="sr-only">商品成本与最终销售单价</caption>
            <colgroup>
              <col className="price-product-col" />
              <col className="price-kind-col" />
              <col className="price-cost-col" />
              <col className="price-k-col" />
              <col className="price-sale-col" />
              <col className="price-remove-col" />
            </colgroup>
            <thead>
              <tr className="price-groups">
                <th colSpan={4} scope="colgroup">商品与成本</th>
                <th colSpan={2} scope="colgroup">销售定价</th>
              </tr>
              <tr className="price-columns">
                <th scope="col">商品名称</th>
                <th scope="col">计价方式</th>
                <th scope="col" className="price-numeric">成本单价</th>
                <th scope="col" className="price-numeric">K</th>
                <th scope="col" className="price-selling-head">最终销售单价</th>
                <th scope="col"><span className="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p, i) => {
                const automatic = p.pricing_mode === "cost_plus";
                const preview =
                  previews[p.id]?.key === previewKey(p)
                    ? previews[p.id]
                    : undefined;
                return (
                  <tr key={p.id}>
                    <td className="price-product-cell">
                      <div className="price-product">
                        <span className="price-index" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                        <Input
                          ref={focusRow === p.id ? newProduct : undefined}
                          aria-label={`商品${i + 1}product_id`}
                          value={p.product_id}
                          placeholder="输入商品名称"
                          maxLength={256}
                          onChange={(e) =>
                            edit(p.id, { product_id: e.target.value })
                          }
                          disabled={app.busy || !supported}
                        />
                      </div>
                    </td>
                    <td className="price-kind-cell">
                      <div className="price-kind-select">
                        <select
                          aria-label={`商品${i + 1}计价方式`}
                          value={p.single ? "single" : "area"}
                          onChange={(e) =>
                            edit(p.id, { single: e.target.value === "single" })
                          }
                          disabled={app.busy || !supported}
                        >
                          <option value="area">面积</option>
                          <option value="single">单件</option>
                        </select>
                        <span className="price-kind-icon"><Icon name="price-chevron" /></span>
                      </div>
                    </td>
                    <td className="price-cost-cell">
                      <Input
                        className="price-numeric"
                        aria-label={`商品${i + 1}cost`}
                        value={p.cost ?? ""}
                        placeholder="—"
                        inputMode="decimal"
                        maxLength={256}
                        onChange={(e) => edit(p.id, { cost: e.target.value })}
                        disabled={app.busy || !supported}
                      />
                    </td>
                    <td className="price-k-cell">
                      <Input
                        className="price-numeric"
                        aria-label={`商品${i + 1}k`}
                        value={p.k}
                        inputMode="decimal"
                        maxLength={256}
                        onChange={(e) => edit(p.id, { k: e.target.value })}
                        disabled={app.busy || !supported}
                      />
                    </td>
                    <td className="price-selling-cell">
                      <div className="sale-editor">
                        <div className="sale-input" data-automatic={automatic}>
                          <span aria-hidden="true">¥</span>
                          <Input
                            className="price-numeric"
                            aria-label={`商品${i + 1}sale`}
                            readOnly={automatic}
                            value={automatic ? (preview?.sale ?? "") : p.sale}
                            placeholder={automatic && !preview ? "计算中…" : "—"}
                            inputMode="decimal"
                            maxLength={256}
                            onChange={(e) => edit(p.id, { sale: e.target.value })}
                            disabled={app.busy || !supported}
                          />
                          <small>{p.single ? "元/件" : "元/㎡"}</small>
                        </div>
                        <label className="cost-price-toggle">
                          <input
                            type="checkbox"
                            aria-label={`商品${i + 1}按成本乘K定价`}
                            checked={automatic}
                            disabled={app.busy || !supported}
                            onChange={(e) =>
                              edit(p.id, {
                                pricing_mode: e.target.checked
                                  ? "cost_plus"
                                  : "manual",
                              })
                            }
                          />
                          成本 × K
                        </label>
                      </div>
                      {automatic && preview?.error && (
                        <p className="inline-error">{preview.error}</p>
                      )}
                    </td>
                    <td className="price-remove-cell">
                      <Button
                        variant="ghost"
                        className="price-remove"
                        aria-label={`移除商品${i + 1}`}
                        title={`移除${p.product_id || "商品"}`}
                        disabled={app.busy || !supported}
                        onClick={() =>
                          setRows((old) => old.filter((row) => row.id !== p.id))
                        }
                      >
                        <span className="price-remove-icon"><Icon name="price-trash" /></span>
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="price-publish-actions">
          <Button
            disabled={app.busy || app.pending || !ready}
            onClick={() => setConfirm(true)}
          >
            发布新版本
          </Button>
        </div>
      </div>
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="发布新价格"
        description={`确认发布这 ${rows.length} 种商品的定价？`}
        compact
        className="price-confirm"
      >
        <div className="dialog-actions">
          <Button variant="outline" onClick={() => setConfirm(false)}>
            返回修改
          </Button>
          <Button
            disabled={app.busy || app.pending || !ready}
            onClick={async () => {
              setConfirm(false);
              await app.publish(
                rows.map((p) => wire(!p.changed && p.source ? p.source : p)),
              );
            }}
          >
            确认发布
          </Button>
        </div>
      </Modal>
    </section>
  );
}
