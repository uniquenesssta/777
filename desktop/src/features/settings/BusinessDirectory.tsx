import { useEffect, useState } from "react";
import { request, errorMessage } from "../../bridge";
import { Button, Field, Input } from "../../ui/components";
import { managedLocation } from "./managedLocations";
type Preference = { directory: string; ledger_id: string; applied: false };
export function BusinessDirectory({ disabled }: { disabled: boolean }) {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void request<Preference>("business_directory")
      .then((r) => {
        if (active) {
          setValue(r.directory);
          setSaved(r.directory);
        }
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const location = managedLocation(value, "manager", "业务数据");
  const locked = disabled || busy;
  return (
    <section className="backup-settings business-directory">
      <h3>业务数据保存位置</h3>
      <div className="directory-choice">
        <Field label="保存位置">
          <Input
            value={location.display}
            readOnly={location.concealed}
            disabled={locked}
            maxLength={32767}
            placeholder="填写希望保存业务数据的位置"
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>
        <Button
          variant="outline"
          disabled={locked || saved === null}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const p = await request<{ directory: string | null }>(
                "pick_directory",
                { target: "business_directory" },
              );
              if (p.directory) setValue(p.directory);
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          选择目录
        </Button>
        {location.concealed && (
          <Button
            variant="ghost"
            disabled={locked}
            onClick={() => setValue("")}
          >
            填写新位置
          </Button>
        )}
      </div>
      <div className="developer-actions">
        <Button
          disabled={locked || saved === null}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const p = await request<Preference>("save_business_directory", {
                directory: value,
              });
              setSaved(p.directory);
              setValue(p.directory);
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          保存位置
        </Button>
        <small className="muted" role="status">
          {saved === null
            ? error
              ? "配置暂不可用"
              : "正在读取配置"
            : value !== saved
              ? "尚未保存"
              : saved
                ? "已保存，暂未应用"
                : "尚未设置"}
        </small>
      </div>
      <p className="muted">
        仅保存在当前电脑。当前业务数据仍由已连接的后台保存。
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
