import "./backup.css";
import "./localOutputs.css";
import {LocalOutputDirectory} from "./LocalOutputDirectory";
import type { Workbench } from "../../state/useWorkbench";
import { stamp } from "../../state/format";
import { Button, Field, Input } from "../../ui/components";
import { backupState } from "./backupPresentation";
import { managedLocation } from "./managedLocations";

export function SettingsPage({ app }: { app: Workbench }) {
  const backupLocation = managedLocation(String(app.backup?.target ?? ""), app.delivery, "每日备份");
  const backupLabel = backupState(app.backup);
  const lastSuccess = app.backup?.last_success as
    | { created_at?: string }
    | null
    | undefined;

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
      <LocalOutputDirectory disabled={app.busy} finance={app.can("finance")}/>
      {app.can("backup") && (
        <section className="backup-settings business-backup">
          <h3>业务数据备份</h3>
          <p className="muted">每天一份可恢复数据和可阅读 Excel；Excel 按月分表，表内按日排列。</p>
          <Field label="备份位置" compact>
            <Input readOnly value={backupLocation.display} />
          </Field>
          {backupLabel && <p className="backup-state">
            状态：
            {backupLabel}{" "}
            · 最近成功：
            {lastSuccess?.created_at ? stamp(lastSuccess.created_at) : "—"}
          </p>}
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
