import { useState } from "react";
import type { Connection } from "../../contracts";
import { request, errorMessage } from "../../bridge";
import { Button, Field, Input } from "../../ui/components";
import "./connection.css";
export function ConnectionForm({
  saved,
  busy,
  submitLabel = "验证并连接",
  onSubmit,
  onCancel,
  onLocal,
}: {
  saved: Connection | null;
  busy: boolean;
  submitLabel?: string;
  onCancel?: () => void;
  onLocal?: () => Promise<unknown>;
  onSubmit: (
    c: Connection,
  ) => Promise<void>;
}) {
  const [connection, setConnection] = useState<Connection>(
    saved ?? { url: "", certificate_pem: "", certificate_sha256: "" },
  );
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [imported, setImported] = useState(false);
  const disabled = busy || working;
  const change = (key: keyof Connection, value: string) => {
    setImported(false);
    setConnection({ ...connection, [key]: value });
  };
  async function importFile() {
    setWorking(true);
    setError("");
    try {
      const picked = await request<{ directory: string | null }>(
        "pick_directory",
        { target: "public_connection" },
      );
      if (!picked.directory) return;
      const result = await request<{ connection: Connection }>(
        "import_connection",
        { path: picked.directory },
      );
      setConnection(result.connection);
      setImported(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setWorking(false);
    }
  }
  return (
    <form
      className="connection-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (disabled) return;
        setWorking(true);
        setError("");
        try {
          await onSubmit(connection);
        } catch (error) {
          setError(errorMessage(error));
        } finally {
          setWorking(false);
        }
      }}
    >
      {onLocal && <Button variant="outline" disabled={disabled} onClick={async()=>{
        setWorking(true);setError("");
        try { await onLocal(); } catch(e) { setError(errorMessage(e)); } finally { setWorking(false); }
      }}>切回本机开发数据</Button>}
      <Button
        variant="outline"
        disabled={disabled}
        onClick={() => void importFile()}
      >
        选择后台连接文件
      </Button>
      <p className="muted connection-help">选择 Host 部署目录 Quote777Service 中的 connection.json，自动读取地址与证书，不导入业务数据。</p>
      {imported && (
        <p className="muted">文件已读取；连接时自动核对后台身份。</p>
      )}
      <Field label="服务地址">
        <Input
          type="url"
          required
          value={connection.url}
          disabled={disabled}
          placeholder="https://电脑地址:端口"
          onChange={(e) => change("url", e.target.value)}
        />
      </Field>
      <details onInvalidCapture={(event) => { event.currentTarget.open = true; }}>
        <summary>证书与指纹（高级）</summary>
        <Field label="服务证书（PEM）">
          <textarea
            required
            rows={4}
            spellCheck={false}
            value={connection.certificate_pem}
            disabled={disabled}
            onChange={(e) => change("certificate_pem", e.target.value)}
          />
        </Field>
        <Field label="证书 SHA-256 指纹">
          <Input
            required
            maxLength={64}
            spellCheck={false}
            value={connection.certificate_sha256}
            disabled={disabled}
            onChange={(e) => change("certificate_sha256", e.target.value)}
          />
        </Field>
      </details>
      <p className="muted connection-help">自动使用默认或已保存的连接身份，无需填写账号密码。</p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        {onCancel && <Button variant="outline" disabled={disabled} onClick={onCancel}>取消</Button>}
        <Button type="submit" disabled={disabled}>
          {working ? "正在核对…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
