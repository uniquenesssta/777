import { useEffect, useState } from "react";
import type { Workbench } from "../state/useWorkbench";
import { stamp } from "../state/format";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
} from "../ui/components";
export function TasksPage({ app }: { app: Workbench }) {
  useEffect(() => {
    if (
      !app.jobs.some((j) =>
        ["queued", "running", "processing", "publishing"].includes(j.state),
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
          导出记录 <small>最近 100 项</small>
        </h2>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.loadJobs()}
        >
          刷新
        </Button>
      </div>
      <p className="muted export-purpose">
        在订单详情点击“导出报价”“报价图片”
        {app.session?.role === "admin" ? "或“内部财务报表”" : ""}
        后，可在这里查看进度和保存结果，失败时重试。
      </p>
      <div className="orders-table-scroll">
        <table className="orders-table">
          <thead>
            <tr>
              <th>导出内容</th>
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
                      重新导出
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!app.jobs.length && (
          <Empty>暂无导出记录，可在订单详情导出Excel或报价图片。</Empty>
        )}
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
  const lastSuccess = app.backup?.last_success as
    | { created_at?: string }
    | null
    | undefined;
  const backupError = app.backup?.last_error ?? app.backup?.error;
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
      {app.delivery === "development" && (
        <>
          <Field label="当前服务">
            <Input readOnly value={app.connection?.url ?? ""} />
          </Field>
          <p className="muted">连接信息由开发配置保存。</p>
          <Button
            variant="outline"
            disabled={app.busy}
            onClick={() => void app.editConnection()}
          >
            开发连接设置
          </Button>
        </>
      )}
      <div className="field">
        <label htmlFor="quote-export-directory">报价表保存位置</label>
        <div className="directory-choice">
          <Input
            id="quote-export-directory"
            value={exportDir}
            title={exportDir}
            readOnly={!admin}
            onChange={(e) => setExport(e.target.value)}
            placeholder="由管理员发布的共享位置"
          />
          {admin && (
            <Button
              variant="outline"
              aria-label="选择报价表保存文件夹"
              disabled={app.busy}
              onClick={async () => {
                const picked = await app.pickDirectory("export_dir");
                if (picked?.directory) setExport(picked.directory);
              }}
            >
              选择文件夹
            </Button>
          )}
        </div>
      </div>
      <div className="field">
        <label htmlFor="quote-image-directory">报价图片保存位置</label>
        <div className="directory-choice">
          <Input
            id="quote-image-directory"
            value={imageDir}
            title={imageDir}
            readOnly={!admin}
            onChange={(e) => setImage(e.target.value)}
            placeholder="由管理员发布的共享位置"
          />
          {admin && (
            <Button
              variant="outline"
              aria-label="选择报价图片保存文件夹"
              disabled={app.busy}
              onClick={async () => {
                const picked = await app.pickDirectory("image_dir");
                if (picked?.directory) setImage(picked.directory);
              }}
            >
              选择文件夹
            </Button>
          )}
        </div>
      </div>
      {admin ? (
        <>
          <p className="muted">
            请选择网络共享文件夹，也可填写共享路径；保存后子版自动继承。
          </p>
          <Button
            onClick={() => app.saveSettings(exportDir, imageDir)}
            disabled={app.busy || !app.preferences}
          >
            发布保存位置
          </Button>
        </>
      ) : (
        <p className="muted">保存位置由管理员发布，当前账号只读继承。</p>
      )}
      {admin && (
        <section className="backup-settings">
          <h3>服务备份</h3>
          <Field label="备份位置">
            <Input readOnly value={String(app.backup?.target ?? "")} />
          </Field>
          <p>
            状态：
            {backupError
              ? "最近备份失败"
              : lastSuccess
                ? "备份正常"
                : "尚无备份"}{" "}
            · 最近成功：
            {lastSuccess?.created_at ? stamp(lastSuccess.created_at) : "—"}
          </p>
          <Button
            variant="outline"
            disabled={app.busy || app.pending}
            onClick={() => void app.makeBackup()}
          >
            生成今日备份
          </Button>
        </section>
      )}
    </section>
  );
}
