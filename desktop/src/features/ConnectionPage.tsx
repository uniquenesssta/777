import type { Connection } from "../contracts";
import { ConnectionForm } from "./connection/ConnectionForm";
export function ConnectionPage({
  error,
  saved,
  busy,
  onConnect,
}: {
  error: string;
  saved: Connection | null;
  busy: boolean;
  onConnect: (c: Connection, u: string, p: string) => Promise<void>;
}) {
  return (
    <main className="connection-page">
      <section className="card connection-card">
        <h1>连接记账器</h1>
        <p className="muted">选择后台连接文件，再验证账号。</p>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <ConnectionForm
          submitLabel="登录"
          saved={saved}
          busy={busy}
          onSubmit={onConnect}
        />
      </section>
    </main>
  );
}
