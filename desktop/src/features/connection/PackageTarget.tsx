import { useEffect, useState } from "react";
import type { Connection } from "../../contracts";
import { request, errorMessage } from "../../bridge";
import { Button, Modal } from "../../ui/components";
import { ConnectionForm } from "./ConnectionForm";
export type TargetState = {
  target: { connection: Connection; ledger_id: string } | null;
  verified: boolean;
};
export function PackageTarget({
  disabled,
  onChange,
}: {
  disabled: boolean;
  onChange: (target: TargetState) => void;
}) {
  const [state, setState] = useState<TargetState>({
    target: null,
    verified: false,
  });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void request<TargetState>("package_target")
      .then((r) => {
        if (active) {
          setState(r);
          onChange(r);
        }
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <section className="package-target">
      <h3>正式封包目标</h3>
      <p className="developer-job-path">
        {state.target?.connection.url ?? "尚未选择 Host"}
      </p>
      <small className="muted">
        {state.target
          ? `账本 ${state.target.ledger_id} · ${state.verified ? "已核对" : "本次启动需重新核对"}`
          : "选择后台连接文件，或使用当前已连接的 Host。"}
      </small>
      <p className="muted">独立保存；切换当前读取的数据不会改变此目标。</p>
      <Button variant="outline" disabled={disabled} onClick={async()=>{
        try {const r=await request<TargetState>("use_current_package_target");setState(r);onChange(r);setError("");}
        catch(e){setError(errorMessage(e));}
      }}>使用当前已连接的 Host</Button>
      <Button
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        {state.target ? "核对或更换目标" : "选择封包目标"}
      </Button>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <Modal open={open} onOpenChange={setOpen} title="选择封包连接的后台" description="设置母版、子版连接的后台；不改变开发版当前数据。" className="connection-dialog">
        <ConnectionForm
          saved={state.target?.connection ?? null}
          busy={disabled}
          submitLabel="核对并保存目标"
          onCancel={() => setOpen(false)}
          onSubmit={async (connection, username, password) => {
            const r = await request<TargetState>("verify_package_target", {
              connection,
              username,
              password,
            });
            setState(r);
            onChange(r);
            setError("");
            setOpen(false);
          }}
        />
      </Modal>
    </section>
  );
}
