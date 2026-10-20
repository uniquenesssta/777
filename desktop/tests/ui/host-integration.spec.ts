// UI-only bridge stand-in. Native storage/ownership/authentication have separate Rust checks.
import { test, expect, type Page } from "@playwright/test";
import { expectSilentFormalEntry } from "../formal-idle.mjs";
async function setup(page: Page, delivery = "manager", registered: boolean | "pending" = true) {
  await page.addInitScript(
    ({ delivery, registered }) => {
      let ready = registered;
      const requests: unknown[] = [];
      (window as any).__integrationRequests = requests;
      const connection = {
        url: "https://192.168.4.23:8477",
        certificate_pem: "public-fixture",
        certificate_sha256: "a".repeat(64),
      };
      const catalog = {
        price_version_id: "test",
        pricing_mode_version: "final-unit-v1",
        items: [],
      };
      const settings = {
        revision: "1",
        export_dir: "D:\\报价文件\\Excel",
        image_dir: "D:\\报价文件\\图片",
      };
      const session = {
        role: delivery === "sales" ? "sales" : "admin",
        subject: "fixture",
        username: "fixture",
        pending: false,
        ledger_id: "00000000-0000-4000-8000-000000000001",
      };
      let callbacks = 1;
      Object.defineProperty(window, "__TAURI_INTERNALS__", {
        value: {
          metadata: {
            currentWindow: { label: "main" },
            currentWebview: { label: "main" },
          },
          transformCallback: () => callbacks++,
          unregisterCallback: () => {},
          invoke: async (command: string, { request: r }: { request: any }) => {
            if (command !== "desktop_action") return 0;
            requests.push(r);
            switch (r.action) {
              case "ui_diagnostic":
                return null;
              case "connection":
                return {
                  delivery,
                  automatic: delivery !== "development",
                  connection: delivery === "development" ? connection : null,
                  pending: false,
                };
              case "bootstrap":
                if (ready === "pending") return new Promise(() => {});
                if (!ready) throw { code: "DEPLOYMENT_NOT_CONFIGURED" };
                return { delivery, automatic: true, session };
              case "connect":
                return { ...session, catalog, settings };
              case "prices":
                return catalog;
              case "settings":
                return settings;
              case "backup_status":
                return {
                  target: "\\\\192.168.4.23\\共享\\backup",
                  last_success: null,
                };
              case "business_directory":
                return {
                  directory: localStorage.getItem("synthetic-directory") ?? "",
                  ledger_id: session.ledger_id,
                  applied: false,
                };
              case "save_business_directory":
                localStorage.setItem("synthetic-directory", r.directory);
                return {
                  directory: r.directory,
                  ledger_id: session.ledger_id,
                  applied: false,
                };
              case "pick_directory":
                return {
                  directory:
                    r.target === "device_enrollment"
                      ? "D:\\设备登记.json"
                      : "D:\\公开连接.json",
                };
              case "import_enrollment":
                ready = true;
                return { registered: true };
              case "import_connection":
                throw { code: "CONNECTION_FILE_WRONG_KIND" };
              default:
                throw { code: "UNEXPECTED_UI_REQUEST" };
            }
          },
        },
      });
    },
    { delivery, registered },
  );
  await page.goto("/");
}
test("manager directory saves locally, survives reload, masks address and keeps output settings separate", async ({
  page,
}, info) => {
  await setup(page);
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  const panel = page.locator(".business-directory");
  const raw = "\\\\192.168.4.23\\共享\\业务数据";
  await panel.getByLabel("保存位置", { exact: true }).fill(raw);
  await expect(panel.getByLabel("保存位置", { exact: true })).toHaveValue(
    "已配置的业务数据位置",
  );
  await panel.getByRole("button", { name: "保存位置", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("已保存，暂未应用");
  const requests = await page.evaluate(
    () => (window as any).__integrationRequests,
  );
  expect(
    requests.filter((r: any) => r.action === "save_business_directory")[0]
      .directory,
  ).toBe(raw);
  expect(
    requests.some((r: any) =>
      ["save_settings", "developer", "backup"].includes(r.action),
    ),
  ).toBe(false);
  await page.reload();
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(
    page.locator(".business-directory").getByRole("status"),
  ).toHaveText("已保存，暂未应用");
  await expect(page.getByLabel("报价表保存位置")).toHaveValue(
    "D:\\报价文件\\Excel",
  );
  await page.setViewportSize({ width: 720, height: 1000 });
  await page.screenshot({
    path: info.outputPath("manager-720.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("sales settings do not acquire business-directory or publication controls", async ({
  page,
}) => {
  await setup(page, "sales");
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(page.locator(".business-directory")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "发布保存位置", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("报价表保存位置")).toHaveAttribute(
    "readonly",
    "",
  );
});
for (const delivery of ["manager", "sales"])
  test(`${delivery} unregistered entry remains silent without account or setup controls`, async ({page}) => {
    await page.clock.install();
    await setup(page, delivery, false);
    await expectSilentFormalEntry(page);
    for (const name of ["账户菜单","退出登录","选择文件","登记并进入","重新连接"])
      await expect(page.getByRole("button",{name,exact:true})).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(/DEPLOYMENT|服务|登记|密码|失败|联系(?:管理员|维护人员)/);
    await page.clock.fastForward(16000);
    const requests=await page.evaluate(()=>(window as any).__integrationRequests);
    expect(requests.filter((r:any)=>r.action==='bootstrap').length).toBeGreaterThanOrEqual(2);
    expect(requests.some((r:any)=>r.action==='import_enrollment')).toBe(false);
  });
for (const delivery of ["manager", "sales"])
  test(`${delivery} pending connection uses the native silent-entry contract`, async ({page}) => {
    await setup(page, delivery, "pending");
    await expectSilentFormalEntry(page);
    const requests = await page.evaluate(() => (window as any).__integrationRequests);
    expect(requests.some((r: any) => r.action === "bootstrap")).toBe(true);
    expect(requests.some((r: any) => ["connect", "import_enrollment"].includes(r.action))).toBe(false);
  });
test("wrong connection-file type preserves the filled connection", async ({
  page,
}) => {
  await setup(page, "development");
  await page
    .getByRole("button", { name: "选择后台连接文件", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("文件用途不匹配");
  await expect(page.getByLabel("服务地址", { exact: true })).toHaveValue(
    "https://192.168.4.23:8477",
  );
});
