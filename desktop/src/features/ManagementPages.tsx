import { useEffect, useState } from "react";
import type { Price } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { stamp } from "../state/format";
import {
  Alert,
  Badge,
  Button,
  Empty,
  Field,
  Input,
  Modal,
} from "../ui/components";
export function PricesPage({ app }: { app: Workbench }) {
  const [items, setItems] = useState<Price[]>(app.catalog?.items ?? []);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => setItems(app.catalog?.items ?? []), [app.catalog]);
  const edit = (i: number, key: keyof Price, value: string | boolean) =>
    setItems((old) =>
      old.map((p, j) => (i === j ? { ...p, [key]: value } : p)),
    );
  return (
    <section className="card management">
      <div className="section-heading">
        <h2>价格维护</h2>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.refreshPrices()}
        >
          重新读取
        </Button>
      </div>
      <p className="muted">发布后新报价使用新版本，已保存订单保持原价。</p>
      <div className="orders-table-scroll">
        <table className="prices-table">
          <thead>
            <tr>
              <th>商品</th>
              <th>销售单价</th>
              <th>成本单价</th>
              <th>K</th>
              <th>计价方式</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((p, i) => (
              <tr key={i}>
                {(["product_id", "sale", "cost", "k"] as const).map((k) => (
                  <td key={k}>
                    <Input
                      aria-label={`商品${i + 1}${k}`}
                      value={p[k] ?? ""}
                      maxLength={256}
                      onChange={(e) => edit(i, k, e.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <select
                    aria-label={`商品${i + 1}计价方式`}
                    value={p.single ? "single" : "area"}
                    onChange={(e) =>
                      edit(i, "single", e.target.value === "single")
                    }
                  >
                    <option value="area">面积</option>
                    <option value="single">单件</option>
                  </select>
                </td>
                <td>
                  <Button
                    variant="ghost"
                    onClick={() => setItems((v) => v.filter((_, j) => j !== i))}
                  >
                    移除
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="add-actions">
        <Button
          variant="outline"
          onClick={() =>
            setItems((v) => [
              ...v,
              { product_id: "", sale: "", cost: "", k: "", single: false },
            ])
          }
          disabled={items.length >= 1000}
        >
          ＋ 添加商品
        </Button>
        <Button
          disabled={app.busy || app.pending || !items.length}
          onClick={() => setConfirm(true)}
        >
          发布新版本
        </Button>
      </div>
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="发布新价格"
        description="确认商品、销售价格、成本与计价方式。已有草稿需要刷新并重算。"
      >
        <div className="dialog-actions">
          <Button variant="outline" onClick={() => setConfirm(false)}>
            返回修改
          </Button>
          <Button
            disabled={app.busy || app.pending}
            onClick={async () => {
              setConfirm(false);
              await app.publish(items);
            }}
          >
            确认发布
          </Button>
        </div>
      </Modal>
    </section>
  );
}
export function TasksPage({ app }: { app: Workbench }) {
  useEffect(() => {
    if (
      !app.jobs.some((j) =>
        ["queued", "running", "processing"].includes(j.state),
      )
    )
      return;
    const timer = setInterval(() => {
      if (!app.busy) void app.loadJobs();
    }, 1500);
    return () => clearInterval(timer);
  }, [app.jobs, app.busy, app.loadJobs]);
  return (
    <section className="card management">
      <div className="section-heading">
        <h2>
          报表与图片任务 <small>最近 100 项</small>
        </h2>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.loadJobs()}
        >
          刷新
        </Button>
      </div>
      <p className="muted">任务与原订单绑定，失败重试不会重复记账。</p>
      <div className="orders-table-scroll">
        <table className="orders-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>订单</th>
              <th>创建时间</th>
              <th>状态</th>
              <th>结果</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {app.jobs.map((j) => (
              <tr key={j.job_id}>
                <td>
                  {{
                    excel_quote: "报价表",
                    excel_admin: "内部财务报表",
                    quote_png: "报价图片",
                  }[j.kind] ?? j.kind}
                </td>
                <td>
                  <Button
                    variant="ghost"
                    onClick={() => void app.readOrder(j.order_id)}
                    disabled={app.busy}
                  >
                    {j.order_id.slice(0, 8)}
                  </Button>
                </td>
                <td>{stamp(j.created_at)}</td>
                <td>
                  <Badge muted={j.state === "failed"}>
                    {{
                      queued: "等待处理",
                      running: "正在处理",
                      publishing: "正在保存",
                      done: "已完成",
                      failed: "失败",
                    }[j.state] ?? j.state}
                  </Badge>
                </td>
                <td>
                  {j.state === "done" ? "已保存到发布位置" : j.error || "—"}
                </td>
                <td>
                  {j.state === "failed" && (
                    <Button
                      variant="outline"
                      disabled={app.busy || app.pending}
                      onClick={() => void app.retryOutput(j.job_id)}
                    >
                      按原任务重试
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!app.jobs.length && <Empty>暂无输出任务。</Empty>}
      </div>
    </section>
  );
}
export function SettingsPage({ app }: { app: Workbench }) {
  const [exportDir, setExport] = useState(app.preferences?.export_dir ?? "");
  const [imageDir, setImage] = useState(app.preferences?.image_dir ?? "");
  const admin = app.session?.role === "admin";
  useEffect(() => {
    setExport(app.preferences?.export_dir ?? "");
    setImage(app.preferences?.image_dir ?? "");
  }, [app.preferences]);
  return (
    <section className="card management settings">
      <div className="section-heading">
        <h2>存储与备份</h2>
        <Button
          variant="ghost"
          onClick={() => void app.loadSettings()}
          disabled={app.busy}
        >
          重新读取
        </Button>
      </div>
      <Field label="当前服务">
        <Input readOnly value={app.connection?.url ?? ""} />
      </Field>
      <p className="muted">连接设置在退出登录后可更改。</p>
      <Field label="报价表保存位置">
        <Input
          value={exportDir}
          readOnly={!admin}
          onChange={(e) => setExport(e.target.value)}
          placeholder="由管理员发布的共享位置"
        />
      </Field>
      <Field label="报价图片保存位置">
        <Input
          value={imageDir}
          readOnly={!admin}
          onChange={(e) => setImage(e.target.value)}
          placeholder="由管理员发布的共享位置"
        />
      </Field>
      {admin ? (
        <>
          <p className="muted">完整填写共享路径，保存后销售端自动继承。</p>
          <Button
            onClick={() => app.saveSettings(exportDir, imageDir)}
            disabled={app.busy || !app.preferences}
          >
            发布保存位置
          </Button>
        </>
      ) : (
        <Alert>保存位置由管理员发布，当前账号只读继承。</Alert>
      )}
      {admin && (
        <section className="backup-settings">
          <h3>服务备份</h3>
          <Field label="备份位置">
            <Input readOnly value={String(app.backup?.target ?? "")} />
          </Field>
          <p>
            状态：{String(app.backup?.status ?? "未读取")} · 最近成功：
            {String(app.backup?.last_success ?? "—")}
          </p>
          <Button
            variant="outline"
            disabled={app.busy || app.pending}
            onClick={() => void app.makeBackup()}
          >
            创建并核对维护备份
          </Button>
        </section>
      )}
    </section>
  );
}
