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
  onConnect: (c: Connection) => Promise<void>;
}) {
  return (
    <main className="connection-page">
      <section className="card connection-card">
        <h1>连接Quote</h1>
        <p className="muted">选择后台连接文件，自动使用默认或已保存的连接身份。</p>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <ConnectionForm
          submitLabel="连接后台"
          saved={saved}
          busy={busy}
          onSubmit={onConnect}
        />
      </section>
    </main>
  );
}
