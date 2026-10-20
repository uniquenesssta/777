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
        image_dir: "D:\\报价文件\\PIC",
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
              case "output_settings": return {root:"D:\\报价文件",export_dir:settings.export_dir,image_dir:settings.image_dir,report_dir:"D:\\报价文件\\内部财务报表"};
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
test("manager settings omit business-directory controls and retain local exports after reload", async ({page}) => {
  await setup(page);
  for (let visit=0; visit<2; visit++) {
    await page.getByRole("button", {name:"存储与备份",exact:true}).click();
    await expect(page.locator(".business-directory")).toHaveCount(0);
    await expect(page.getByRole("heading",{name:"业务数据保存位置",exact:true})).toHaveCount(0);
    await expect(page.getByRole("button",{name:"保存位置",exact:true})).toHaveCount(0);
    await expect(page.getByRole("button",{name:"选择目录",exact:true})).toHaveCount(0);
    await expect(page.getByLabel("导出文件保存位置")).toHaveValue("D:\\报价文件");
    await expect(page.locator(".local-output-folders")).toContainText("PIC");
    const requests = await page.evaluate(() => (window as any).__integrationRequests);
    expect(requests.some((r:any)=>["business_directory","save_business_directory"].includes(r.action))).toBe(false);
    if (visit===0) await page.reload();
  }
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
  await expect(page.getByLabel("导出文件保存位置")).toHaveAttribute(
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
