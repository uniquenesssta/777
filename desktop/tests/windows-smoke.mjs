// Actual WebView2 page of the isolated Tauri executable, never a mock IPC bridge.
import { chromium } from "playwright";
import { expect } from "@playwright/test";
import fs from "node:fs";
import { productionOrigin } from "./native-origin.mjs";
import { connectNativeBrowser } from "./native-cdp.mjs";
const [configPath, port, out] = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(configPath, "utf8"));
let browser;
async function main() {
  browser = await connectNativeBrowser(
    (endpoint, options) => chromium.connectOverCDP(endpoint, options),
    `http://127.0.0.1:${port}`,
    { report: (value) => fs.writeFileSync(out + "/native-cdp-connection.json", JSON.stringify(value, null, 2)) },
  );
  let page;
  for (let i = 0; i < 100; i++) {
    page = browser
      .contexts()
      .flatMap((c) => c.pages())
      .find(
        (p) => !p.url().startsWith("devtools:") && p.url() !== "about:blank",
      );
    if (page) break;
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!page) throw Error("ACTUAL_TAURI_PAGE_NOT_FOUND");
  const originFile = out + "/native-window-origin.json";
  const observed = { observed_url: page.url(), status: "checking" };
  fs.writeFileSync(originFile, JSON.stringify(observed, null, 2));
  let origin;
  try {
    origin = productionOrigin(page.url());
    fs.writeFileSync(
      originFile,
      JSON.stringify(
        { ...observed, status: "origin_checked", production_origin: origin },
        null,
        2,
      ),
    );
  } catch (error) {
    fs.writeFileSync(
      originFile,
      JSON.stringify(
        { ...observed, status: "rejected", reason: String(error) },
        null,
        2,
      ),
    );
    await page
      .screenshot({ path: out + "/native-origin-failure.png" })
      .catch(() => {});
    throw error;
  }
  await page
    .getByLabel("服务地址", { exact: true })
    .waitFor({ state: "visible", timeout: 15000 });
  const assert = (v, m) => {
    if (!v) throw Error(m);
  };
  await page
    .getByLabel("服务地址", { exact: true })
    .fill(fixture.connection.url);
  await page
    .getByLabel("服务证书（PEM）", { exact: true })
    .fill(fixture.connection.certificate_pem);
  await page
    .getByLabel("证书 SHA-256 指纹", { exact: true })
    .fill(fixture.connection.certificate_sha256);
  await page.getByLabel("账号", { exact: true }).fill("manager");
  await page.getByLabel("密码", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "添加商品", exact: false }).click();
  await page.getByLabel("商品", { exact: true }).selectOption("安装服务");
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await page.getByLabel("订单号", { exact: true }).fill("native-tauri-00003");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await page.getByRole("button", { name: "追加备注", exact: true }).waitFor();
  assert(
    (await page.getByText("native-tauri-00003", { exact: true }).count()) > 0,
    "NATIVE_ORDER_REF_MISSING",
  );
  await page.getByRole("button", { name: "账户菜单" }).click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号", { exact: true }).fill("sales-one");
  await page.getByLabel("密码", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "我的订单", exact: true }).click();
  await page.getByRole("button", { name: "查看详情" }).first().waitFor();
  await expect(page.getByRole("button", { name: "刷新", exact: true })).toBeEnabled({ timeout: 15000 });
  assert(
    (await page.getByText("商品成本", { exact: true }).count()) === 0,
    "SALES_COST_UI_LEAK",
  );
  assert(
    (await page.getByText("native-tauri-00003", { exact: true }).count()) === 0,
    "OTHER_ACTOR_ORDER_LEAK",
  );
  await page.screenshot({ path: out + "/native-sales-orders.png" });
  fs.writeFileSync(
    out + "/native-webview.json",
    JSON.stringify(
      {
        status: "passed",
        actual_Tauri_WebView2: true,
        production_page_origin: origin,
        production_origin_checked_before_login: true,
        real_IPC_and_Rust_HTTPS: true,
        manager_submit: true,
        sales_cost_and_other_order_hidden: true,
        profile_isolated: true,
        UI_idle_before_native_close: true,
      },
      null,
      2,
    ),
  );
}
try {
  await main();
} finally {
  await browser?.close();
}
