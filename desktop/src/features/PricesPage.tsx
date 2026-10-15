import { useEffect, useState } from "react";
import type { Price } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { request } from "../bridge";
import { Button, Input, Modal } from "../ui/components";

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
  const supported = app.catalog?.pricing_mode_version === "final-unit-v1";
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
        p.pricing_mode !== "cost_plus" ||
        (previews[p.id]?.key === previewKey(p) &&
          previews[p.id]?.sale !== undefined),
    );
  return (
    <section className="card management price-maintenance">
      <div className="section-heading">
        <h2>
          价格维护 <small>{rows.length} 种商品</small>
        </h2>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.refreshPrices()}
        >
          重新读取
        </Button>
      </div>
      <p className="muted">发布后新报价使用新版本，已保存订单保持原价。</p>
      {!supported && (
        <p className="inline-error">
          当前服务不支持新的定价方式，请更新服务后重新读取。
        </p>
      )}
      <div className="orders-table-scroll">
        <table className="price-editor">
          <colgroup>
            <col className="price-product-col" />
            <col className="price-kind-col" />
            <col className="price-cost-col" />
            <col className="price-k-col" />
            <col className="price-sale-col" />
            <col className="price-remove-col" />
          </colgroup>
          <thead>
            <tr>
              <th>商品</th>
              <th>计价方式</th>
              <th className="price-numeric">成本单价</th>
              <th className="price-numeric">K</th>
              <th className="price-selling-head">销售单价</th>
              <th />
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
                  <td>
                    <Input
                      aria-label={`商品${i + 1}product_id`}
                      value={p.product_id}
                      maxLength={256}
                      onChange={(e) =>
                        edit(p.id, { product_id: e.target.value })
                      }
                      disabled={app.busy || !supported}
                    />
                  </td>
                  <td>
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
                  </td>
                  <td>
                    <Input
                      className="price-numeric"
                      aria-label={`商品${i + 1}cost`}
                      value={p.cost ?? ""}
                      maxLength={256}
                      onChange={(e) => edit(p.id, { cost: e.target.value })}
                      disabled={app.busy || !supported}
                    />
                  </td>
                  <td>
                    <Input
                      className="price-numeric"
                      aria-label={`商品${i + 1}k`}
                      value={p.k}
                      maxLength={256}
                      onChange={(e) => edit(p.id, { k: e.target.value })}
                      disabled={app.busy || !supported}
                    />
                  </td>
                  <td className="price-selling-cell">
                    <div className="sale-editor">
                      <div className="sale-input">
                        <Input
                          className="price-numeric"
                          aria-label={`商品${i + 1}sale`}
                          readOnly={automatic}
                          value={automatic ? (preview?.sale ?? "") : p.sale}
                          placeholder={automatic && !preview ? "计算中…" : ""}
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
                              ...(!e.target.checked &&
                              preview?.sale !== undefined
                                ? { sale: preview.sale }
                                : {}),
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
                  <td>
                    <Button
                      variant="ghost"
                      aria-label={`移除商品${i + 1}`}
                      disabled={app.busy || !supported}
                      onClick={() =>
                        setRows((old) => old.filter((row) => row.id !== p.id))
                      }
                    >
                      移除
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="add-actions">
        <Button
          variant="outline"
          disabled={app.busy || !supported || rows.length >= 1000}
          onClick={() =>
            setRows((old) => [
              ...old,
              {
                id: crypto.randomUUID(),
                product_id: "",
                sale: "",
                cost: "",
                k: "1",
                single: false,
                pricing_mode: "manual",
                changed: true,
              },
            ])
          }
        >
          ＋ 添加商品
        </Button>
        <Button
          disabled={app.busy || app.pending || !ready}
          onClick={() => setConfirm(true)}
        >
          发布新版本
        </Button>
      </div>
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="发布新价格"
        description="确认商品与最终销售单价。已有草稿需要重新计算。"
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
