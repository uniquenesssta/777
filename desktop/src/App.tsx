import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { useWorkbench, type Route } from "./state/useWorkbench";
import { QuotePage } from "./features/QuotePage";
import { OrdersPage } from "./features/OrdersPage";
import { DetailPage } from "./features/DetailPage";
import { ConnectionPage } from "./features/ConnectionPage";
import {
  PricesPage,
  SettingsPage,
  TasksPage,
} from "./features/ManagementPages";
import { Alert, Button, Icon } from "./ui/components";
export default function App() {
  const app = useWorkbench();
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
  const [closeBlocked, setCloseBlocked] = useState(false);
  const [fontFallback, setFontFallback] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([document.fonts.load('14px "Noto Sans SC"'), document.fonts.load('14px Inter')])
      .catch(() => { if (active) setFontFallback(true); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const listener = listen("close-blocked", () => setCloseBlocked(true)).catch(
      () => () => {},
    );
    return () => {
      void listener.then((unlisten) => unlisten());
    };
  }, []);
  const extra: { route: Route; label: string; admin?: boolean }[] = [
    { route: "prices", label: "价格维护", admin: true },
    { route: "profit", label: "利润分析", admin: true },
    { route: "tasks", label: "报表与图片任务" },
    { route: "settings", label: "存储与备份" },
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
        {app.session && (
          <>
            <nav aria-label="主导航">
              <Button
                variant={app.route === "quote" ? "primary" : "ghost"}
                onClick={() => nav("quote")}
              >
                报价工作台
              </Button>
              <Button
                variant={
                  ["orders", "detail"].includes(app.route) ? "primary" : "ghost"
                }
                onClick={() => nav("orders")}
              >
                {app.session.role === "admin" ? "订单记录" : "我的订单"}
              </Button>
              {extra
                .filter((i) => !i.admin || app.session?.role === "admin")
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
            <div className="account" ref={account} onKeyDown={event=>{
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
            </div>
          </>
        )}
      </header>
      {app.feedback && (
        <div className="feedback-wrap">
          <Alert error={app.isError}>{app.feedback}</Alert>
        </div>
      )}
      {fontFallback && <div className="feedback-wrap"><Alert>字体资源加载失败，当前使用系统字体。</Alert></div>}
      {closeBlocked && (
        <div className="feedback-wrap">
          <Alert>
            订单或设置正在保存，请等待完成后关闭。
            <Button variant="ghost" onClick={() => setCloseBlocked(false)}>
              知道了
            </Button>
          </Alert>
        </div>
      )}
      {app.session && app.pending && (
        <div className="feedback-wrap">
          <Alert error>
            有结果未知的原请求。
            <Button
              variant="outline"
              disabled={app.busy}
              onClick={() => void app.recover(false)}
            >
              核查原请求
            </Button>
            <Button
              variant="outline"
              disabled={app.busy}
              onClick={() => void app.recover(true)}
            >
              按原请求重试
            </Button>
          </Alert>
        </div>
      )}
      {!app.session ? app.delivery === "loading" || app.automatic ? (
        <main className="connection-page"><section className="card connection-card" aria-busy={app.busy}>
          <h1>{app.busy || app.delivery === "loading" ? "正在连接…" : "暂时无法进入记账器"}</h1>
          <p className="muted">{app.busy || app.delivery === "loading" ? "请稍候" : "请重试；仍无法连接时请联系管理员。输入草稿会保留。"}</p>
          <Button disabled={app.busy || app.delivery === "loading"} onClick={()=>void app.bootstrap()}>重新连接</Button>
        </section></main>
      ) : (
        <ConnectionPage
          key={app.connection?.url ?? "initial"}
          saved={app.connection}
          busy={app.busy}
          onConnect={app.connect}
        />
      ) : (
        <main className="workspace" aria-busy={app.busy} tabIndex={-1}>
          {app.route === "quote" && <QuotePage app={app} />}{" "}
          {app.route === "orders" && <OrdersPage app={app} />}{" "}
          {app.route === "detail" && <DetailPage app={app} />}{" "}
          {app.route === "prices" && app.session.role === "admin" && (
            <PricesPage app={app} />
          )}{" "}
          {app.route === "profit" && app.session.role === "admin" && (
            <OrdersPage app={app} profit />
          )}{" "}
          {app.route === "tasks" && <TasksPage app={app} />}{" "}
          {app.route === "settings" && <SettingsPage app={app} />}
        </main>
      )}
    </>
  );
}
