import { useEffect, useRef, useState } from "react";
import { useWorkbench, type Route } from "./state/useWorkbench";
import { QuotePage } from "./features/QuotePage";
import { PricesPage } from "./features/PricesPage";
import { ProfitPage } from "./features/ProfitPage";
import { OrdersPage } from "./features/OrdersPage";
import { DetailPage } from "./features/DetailPage";
import { ConnectionForm } from "./features/connection/ConnectionForm";
import { ConnectionPage } from "./features/ConnectionPage";
import { DeveloperPage } from "./features/DeveloperPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { TasksPage } from "./features/TasksPage";
import { Button, Icon, Modal } from "./ui/components";
// A formal installer never embeds the developer connection/login form.
const formalPackage = import.meta.env.VITE_QUOTE777_DELIVERY === "manager" ||
  import.meta.env.VITE_QUOTE777_DELIVERY === "sales";
export default function App() {
  const app = useWorkbench();
  const businessApp = {...app, busy:app.businessBusy};
  const [menu, setMenu] = useState(false);
  const account = useRef<HTMLDivElement>(null);
  const accountTrigger = useRef<HTMLButtonElement>(null);
  const logoutButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menu) return;
    logoutButton.current?.focus();
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !account.current?.contains(event.target)) setMenu(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [menu]);
  const extra: { route: Route; label: string; admin?: boolean }[] = [
    { route: "prices", label: "价格维护", admin: true },
    { route: "profit", label: "利润分析", admin: true },
    { route: "tasks", label: "导出记录" },
    { route: "settings", label: "存储与备份" },
    ...(!formalPackage && app.developerTools ? [{ route: "developer" as Route, label: "开发者工具" }] : []),
  ];
  const nav = (route: Route) => {
    setMenu(false);
    app.navigate(route);
  };
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span>记</span>
          <strong>记账器</strong>
        </div>
        {app.workspaceVisible && (
          <>
            <nav aria-label="主导航">
              <Button
                variant={app.route === "quote" ? "primary" : "ghost"}
                onClick={() => nav("quote")}
              >
                报价工作台
              </Button>
              {app.can("orders") && <Button
                variant={
                  ["orders", "detail"].includes(app.route) ? "primary" : "ghost"
                }
                onClick={() => nav("orders")}
              >
                {app.navigationRole === "admin" ? "订单记录" : "我的订单"}
              </Button>}
              {extra
                .filter((i) => (!i.admin || app.navigationRole === "admin") && (i.route === "developer" || app.can(({prices:"prices",profit:"finance",tasks:"exports",settings:"settings"} as const)[i.route as "prices"|"profit"|"tasks"|"settings"])))
                .map((i) => (
                  <Button
                    variant={app.route === i.route ? "primary" : "ghost"}
                    key={i.route}
                    onClick={() => nav(i.route)}
                  >
                    {i.label}
                  </Button>
                ))}
            </nav>
            {!formalPackage && !app.formal && app.session && <div className="account" ref={account} onKeyDown={event=>{
              if (event.key === "Escape" && menu) { setMenu(false); accountTrigger.current?.focus(); }
            }} onBlur={event=>{if (!event.currentTarget.contains(event.relatedTarget)) setMenu(false);}}>
              <button
                ref={accountTrigger}
                className="account-trigger"
                aria-expanded={menu}
                aria-label="账户菜单"
                aria-controls={menu ? "account-actions" : undefined}
                onClick={() => setMenu(!menu)}
              >
                <span title={app.session.username}>{app.session.username}</span>
                <b>{app.session.role === "admin" ? "管" : "销"}</b>
                <Icon name="chevron" />
              </button>
              {menu && (
                <div className="account-menu" id="account-actions">
                  <Button
                    ref={logoutButton}
                    variant="ghost"
                    disabled={app.busy}
                    onClick={() => {
                      setMenu(false);
                      void app.logout();
                    }}
                  >
                    退出登录
                  </Button>
                </div>
              )}
            </div>}
          </>
        )}
      </header>
      {!formalPackage && app.developerTools && app.route === "developer" ? <main className="workspace" aria-busy={app.busy} tabIndex={-1}><DeveloperPage app={app}/></main> : !app.workspaceVisible ? formalPackage || ["manager","sales"].includes(app.delivery) ? <main className="formal-idle" aria-label="记账器" /> : app.delivery === "loading" || app.automatic ? (
        <main className="connection-page"><section className="card connection-card" aria-busy={app.busy}>
          <h1>{app.busy || app.delivery === "loading" ? "正在连接…" : "暂时无法进入记账器"}</h1>
          <p className="muted">{app.busy || app.delivery === "loading" ? "请稍候" : "请重试；仍无法连接时请联系管理员。输入草稿会保留。"}</p>
          <Button disabled={app.busy || app.delivery === "loading"} onClick={()=>void app.bootstrap()}>重新连接</Button>
        </section></main>
      ) : (
        <ConnectionPage
          key={app.connection?.url ?? "initial"}
          error={app.isError ? app.feedback : ""}
          saved={app.connection}
          busy={app.busy}
          onConnect={app.connect}
        />
      ) : (
        <main className="workspace" aria-busy={app.busy} tabIndex={-1}>
          {app.isError && app.feedback && (
            <p className="inline-error" role="alert">{app.feedback}</p>
          )}
          {app.route === "quote" && <QuotePage app={businessApp} />}{" "}
          {app.route === "orders" && app.can("orders") && <OrdersPage app={businessApp} />}{" "}
          {app.route === "detail" && app.can("orders") && <DetailPage app={businessApp} />}{" "}
          {app.route === "prices" && app.can("prices") && (
            <PricesPage app={businessApp} />
          )}{" "}
          {app.route === "profit" && app.can("finance") && (
            <ProfitPage app={businessApp} />
          )}{" "}
          {app.route === "tasks" && app.can("exports") && <TasksPage app={businessApp} />}{" "}
          {app.route === "settings" && app.can("settings") && <SettingsPage app={businessApp} />}
        </main>
      )}
    {!formalPackage && app.delivery==="development" && <Modal open={app.connectionDialog} onOpenChange={v=>!v&&app.closeConnectionDialog()} title="连接后台服务" description="选择开发版要读取的在线后台。" className="connection-dialog"><ConnectionForm saved={app.connection} busy={app.busy} onCancel={app.closeConnectionDialog} onSubmit={app.connect} onLocal={app.developerTools ? app.connectLocal : undefined}/></Modal>}
    <Modal open={!!app.draftChange} onOpenChange={(v)=>!v&&app.cancelDraftChange()} title="尚有未保存的修改" description="继续当前编辑，或放弃草稿并切换。" compact>
        <div className="dialog-actions"><Button variant="outline" onClick={app.resumeDraft}>继续编辑</Button><Button onClick={app.confirmDraftChange}>放弃修改</Button></div>
      </Modal>
      </>
  );
}
