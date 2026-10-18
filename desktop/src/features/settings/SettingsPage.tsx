import { useEffect, useState } from "react";
import type { Workbench } from "../../state/useWorkbench";
import { stamp } from "../../state/format";
import { Button, Field, Input } from "../../ui/components";
import { BusinessDirectory } from "./BusinessDirectory";
import { managedLocation } from "./managedLocations";

export function SettingsPage({ app }: { app: Workbench }) {
  const [exportDir, setExport] = useState(app.preferences?.export_dir ?? "");
  const [imageDir, setImage] = useState(app.preferences?.image_dir ?? "");
  const admin = app.session?.role === "admin";
  const exportLocation = managedLocation(exportDir, app.delivery, "报价表");
  const imageLocation = managedLocation(imageDir, app.delivery, "报价图片");
  const backupLocation = managedLocation(String(app.backup?.target ?? ""), app.delivery, "每日备份");
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
      {admin && app.delivery === "manager" && <BusinessDirectory disabled={app.busy}/> }
      <div className="field">
        <label htmlFor="quote-export-directory">报价表保存位置</label>
        <div className="directory-choice">
          <Input
            id="quote-export-directory"
            value={exportLocation.display}
            title={exportLocation.display}
            readOnly={!admin || exportLocation.concealed}
            onChange={(e) => setExport(e.target.value)}
            placeholder="由管理员发布的保存位置"
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
            value={imageLocation.display}
            title={imageLocation.display}
            readOnly={!admin || imageLocation.concealed}
            onChange={(e) => setImage(e.target.value)}
            placeholder="由管理员发布的保存位置"
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
            请选择保存文件夹，也可填写完整路径；保存后子版自动继承。
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
      {app.can("backup") && (
        <section className="backup-settings">
          <h3>服务备份</h3>
          <Field label="备份位置">
            <Input readOnly value={backupLocation.display} />
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
