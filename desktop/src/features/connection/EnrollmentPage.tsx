import { useState } from "react";
import type { Workbench } from "../../state/useWorkbench";
import { errorMessage, request } from "../../bridge";
import { managedLocation } from "../settings/managedLocations";
import { Button, Field, Input } from "../../ui/components";
export function EnrollmentPage({ app }: { app: Workbench }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const working = busy || app.busy || app.delivery === "loading";
  const location = managedLocation(path, app.delivery, "登记文件");
  return (
    <main className="connection-page">
      <section className="card connection-card" aria-busy={working}>
        <h1>
          {app.busy || app.delivery === "loading"
            ? "正在连接…"
            : "欢迎使用记账器"}
        </h1>
        <p className="muted">
          {app.delivery === "sales" ? "子版" : "母版"} · 设备登记
        </p>
        <p>
          首次使用时，选择管理员为这台电脑准备的登记文件。完成后日常自动连接。
        </p>
        <div className="directory-choice">
          <Field label="登记文件">
            <Input
              readOnly
              value={location.display}
              placeholder="请选择设备登记文件"
            />
          </Field>
          <Button
            variant="outline"
            disabled={working}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const p = await request<{ directory: string | null }>(
                  "pick_directory",
                  { target: "device_enrollment" },
                );
                if (p.directory) setPath(p.directory);
              } catch (e) {
                setError(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            选择文件
          </Button>
        </div>
        {(error || app.isError) && (
          <p className="inline-error" role="alert">
            {error || app.feedback}
          </p>
        )}
        <div className="developer-actions">
          <Button
            disabled={working || !path}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await request("import_enrollment", { path });
                await app.bootstrap();
              } catch (e) {
                setError(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "正在登记…" : "登记并进入"}
          </Button>
          <Button
            variant="outline"
            disabled={working}
            onClick={() => void app.bootstrap()}
          >
            重新连接
          </Button>
        </div>
        <small className="muted">
          已有设备请先重新连接。登记失效时，请管理员重新签发此版本的设备登记文件。
        </small>
      </section>
    </main>
  );
}
