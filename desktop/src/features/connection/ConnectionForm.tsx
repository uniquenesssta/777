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
}: {
  saved: Connection | null;
  busy: boolean;
  submitLabel?: string;
  onCancel?: () => void;
  onSubmit: (
    c: Connection,
    username: string,
    password: string,
  ) => Promise<void>;
}) {
  const [connection, setConnection] = useState<Connection>(
    saved ?? { url: "", certificate_pem: "", certificate_sha256: "" },
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
        const secret = password;
        setPassword("");
        try {
          await onSubmit(connection, username, secret);
        } catch (error) {
          setError(errorMessage(error));
        } finally {
          setWorking(false);
        }
      }}
    >
      <Button
        variant="outline"
        disabled={disabled}
        onClick={() => void importFile()}
      >
        选择后台连接文件
      </Button>
      <p className="muted connection-help">选择 Host 部署目录 Quote777Service 中的 connection.json，自动读取地址与证书，不导入业务数据。</p>
      {imported && (
        <p className="muted">文件已读取；输入管理员账号后核对服务身份。</p>
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
      <div className="form-pair">
        <Field label="账号">
          <Input
            required
            autoComplete="username"
            disabled={disabled}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <Field label="密码">
          <Input
            required
            type="password"
            autoComplete="current-password"
            disabled={disabled}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
      </div>
      <p className="muted connection-help">使用后台管理员账号；不是 Windows 登录密码。</p>
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
