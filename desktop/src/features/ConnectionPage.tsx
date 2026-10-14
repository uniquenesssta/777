import { useState } from "react";
import type { Connection } from "../contracts";
import { Button, Field, Input } from "../ui/components";
export function ConnectionPage({
  saved,
  busy,
  onConnect,
}: {
  saved: Connection | null;
  busy: boolean;
  onConnect: (c: Connection, u: string, p: string) => Promise<void>;
}) {
  const [url, setUrl] = useState(saved?.url ?? "");
  const [pem, setPem] = useState(saved?.certificate_pem ?? "");
  const [pin, setPin] = useState(saved?.certificate_sha256 ?? "");
  const [username, setUser] = useState("");
  const [password, setPassword] = useState("");
  return (
    <main className="connection-page">
      <form
        className="card connection-card"
        onSubmit={(e) => {
          e.preventDefault();
          const secret = password;
          setPassword("");
          void onConnect(
            { url, certificate_pem: pem, certificate_sha256: pin },
            username,
            secret,
          );
        }}
      >
        <h1>连接记账器</h1>
        <p className="muted">使用已配置的服务地址和账号登录。</p>
        <Field label="服务地址">
          <Input
            type="url"
            placeholder="https://电脑地址:端口"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
          />
        </Field>
        <Field label="服务证书（PEM）">
          <textarea
            aria-label="服务证书（PEM）"
            value={pem}
            onChange={(e) => setPem(e.target.value)}
            rows={4}
            required
            spellCheck={false}
          />
        </Field>
        <Field label="证书 SHA-256 指纹">
          <Input
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            required
            maxLength={64}
            spellCheck={false}
          />
        </Field>
        <div className="form-pair">
          <Field label="账号">
            <Input
              autoComplete="username"
              value={username}
              onChange={(e) => setUser(e.target.value)}
              required
            />
          </Field>
          <Field label="密码">
            <Input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
        </div>
        <Button type="submit" disabled={busy}>
          {busy ? "正在连接…" : "登录"}
        </Button>
      </form>
    </main>
  );
}
