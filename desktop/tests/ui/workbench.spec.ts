import { test, expect } from "@playwright/test";
const host = "http://127.0.0.1:18777";
let fixture: {
  connection: Record<string, string>;
  username: string;
  password: string;
};
test.beforeEach(async ({ page, request }) => {
  const r = await request.post(host + "/reset", { data: {} });
  expect(r.ok()).toBeTruthy();
  fixture = await r.json();
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const style = document.createElement("style");
      style.textContent =
        "@font-face{font-family:'Noto Sans SC';font-style:normal;font-weight:100 900;src:url('http://127.0.0.1:18777/font.ttf')}";
      document.head.appendChild(style);
    });
    const callbacks = new Map();
    let next = 1;
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      value: {
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main" },
        },
        transformCallback: (f: unknown) => {
          callbacks.set(next, f);
          return next++;
        },
        unregisterCallback: (id: number) => callbacks.delete(id),
        invoke: async (cmd: string, args: { request: unknown }) => {
          if (cmd !== "desktop_action") return 0;
          const r = await fetch("http://127.0.0.1:18777/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(args.request),
          });
          const v = await r.json();
          if (v.error) throw v.error;
          return v.ok;
        },
      },
    });
  });
});
test.afterAll(async ({ request }) => {
  const r = await request.post(host + "/cleanup", { data: {} });
  expect(await r.json()).toEqual({ sandbox_cleaned: true });
});

test("profit charts use the full real ledger across order pages", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "利润分析", exact: true }).click();
  await expect(
    page.getByText("有效订单 25 笔", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "收入成本利润柱状图" }),
  ).toBeVisible();
  await expect(page.locator(".analysis-metrics")).toContainText("2,500.00");
  await expect(page.locator(".analysis-metrics")).toContainText("1,250.00");
  await page.getByRole("button", { name: "折线图", exact: true }).click();
  await expect(page.getByRole("region", { name: "收入成本利润折线图" })).toBeVisible();
  await page.getByRole("button", { name: "饼图", exact: true }).click();
  await expect(page.getByRole("img", { name: /盈利1,250.00元，占比100.0%/ })).toBeVisible();
  await page.getByRole("button", { name: "K线图", exact: true }).click();
  await expect(page.getByRole("img", { name: /25笔，开0.00，高1,250.00，低0.00，收1,250.00/ })).toBeVisible();
});
async function login(
  page: import("@playwright/test").Page,
  username = "manager",
) {
  await page.goto("/");
  await page
    .getByLabel("服务地址", { exact: true })
    .fill(fixture.connection.url);
  await page
    .getByLabel("服务证书（PEM）", { exact: true })
    .fill(fixture.connection.certificate_pem);
  await page
    .getByLabel("证书 SHA-256 指纹", { exact: true })
    .fill(fixture.connection.certificate_sha256);
  await page.getByLabel("账号", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "添加商品", exact: false }),
  ).toBeEnabled();
}
async function add(
  page: import("@playwright/test").Page,
  product = "安装服务",
) {
  await page.getByRole("button", { name: "添加商品", exact: false }).click();
  await page.getByLabel("商品", { exact: true }).selectOption(product);
  await page.getByRole("button", { name: "添加", exact: true }).click();
}
test("real Rust quote, compact confirmation, append note, void/restore and full pagination", async ({
  page,
}) => {
  await login(page);
  await add(page);
  await page.getByLabel("订单号", { exact: true }).fill("00003");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "核对并提交订单" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible();
  expect((await modal.boundingBox())!.width).toBe(380);
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "追加备注", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "追加备注", exact: true }).click();
  await page.getByLabel("备注内容").fill("原备注保留 00003");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(
    page.getByText("原备注保留 00003", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "作废订单", exact: true }).click();
  await page.getByLabel("操作原因").fill("测试作废");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "恢复订单", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "恢复订单", exact: true }).click();
  await page.getByLabel("操作原因").fill("测试恢复");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(
    page.getByText("原备注保留 00003", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "返回订单记录", exact: true }).click();
  await expect(page.getByRole("button", { name: "下一页" })).toBeEnabled();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/manager-orders.png" });
});
test("input edit invalidates result and late calculation cannot reenable submit", async ({
  page,
}) => {
  await login(page);
  await add(page);
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "核对并提交订单" }),
  ).toBeVisible();
  await page.getByLabel("第1行数量").fill("2");
  await expect(
    page.getByRole("button", { name: "计算报价", exact: true }),
  ).toBeVisible();
  await page.getByLabel("第1行数量").fill("1/0");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(page.locator(".inline-error")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "核对并提交订单" }),
  ).toHaveCount(0);
});
test("sales DTO and pages contain no cost/profit and settings inherit", async ({
  page,
}) => {
  const responses: unknown[] = [];
  page.on("response", async (r) => {
    if (r.url().endsWith("/action")) responses.push(await r.json());
  });
  await login(page, "sales-one");
  await add(page);
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "核对并提交订单" }),
  ).toBeVisible();
  await expect(page.getByText("商品成本", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "我的订单", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看详情" }).first(),
  ).toBeEnabled();
  await expect(page.getByText("00024", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "价格维护", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(page.getByLabel("报价表保存位置")).toHaveAttribute(
    "readonly",
    "",
  );
  expect(JSON.stringify(responses)).not.toMatch(
    /cost_cents|profit_cents|financial_display|"cost"/,
  );
  await page.screenshot({ path: "test-results/sales-settings.png" });
});
test("unknown commit requires original receipt check and restart never double books", async ({
  page,
  request,
}) => {
  await login(page);
  await add(page);
  await page.getByLabel("订单号", { exact: true }).fill("unknown-original");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await request.post(host + "/fault-after-commit", { data: {} });
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByRole("button", { name: "核查原请求" })).toBeVisible();
  await request.post(host + "/restart", { data: {} });
  await page.getByRole("button", { name: "核查原请求" }).click();
  await expect(page.getByRole("button", { name: "核查原请求" })).toHaveCount(0);
  await page.getByRole("button", { name: "订单记录", exact: true }).click();
  await page.getByLabel("搜索订单").fill("unknown-original");
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  await expect(page.getByRole("button", { name: "查看详情" })).toHaveCount(1);
});
test("current Figma quote geometry and all original assets load at their exported sizes", async ({
  page,
}) => {
  const lines = [
    { product_id: "户外写真", h: "2", w: "3", q: "1" },
    { product_id: "户外写真", h: "2", w: "3", q: "1" },
    { product_id: "户外写真", h: "2", w: "3", q: "2" },
    { product_id: "PVC 硬板", h: "1.2", w: "2.4", q: "1" },
    { product_id: "PVC 硬板", h: "1.2", w: "2.4", q: "2" },
    { product_id: "安装服务", h: "", w: "", q: "1" },
  ].map((p, i) => ({
    id: "sample" + i,
    raw: { line_kind: "normal", name: "", ...p },
  }));
  await page.addInitScript(
    (lines) =>
      localStorage.setItem(
        "777-desktop-draft-v1",
        JSON.stringify({
          schema: "777-desktop-draft-v1",
          details: {
            customer: "青禾工作室（示例）",
            order_ref: "QH-20261013",
            wechat: "qinghe_demo",
          },
          lines: [
            ...lines,
            {
              id: "discount",
              raw: { line_kind: "discount", percent: "95%", name: "" },
            },
          ],
        }),
      ),
    lines,
  );
  await login(page);
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(page.getByText("1,248.68", { exact: true })).toBeVisible();
  const box = await page.locator(".quote-card").boundingBox();
  expect(box!.x).toBe(40);
  expect(box!.y).toBe(104);
  expect(box!.height).toBe(748);
  const assets = await page.locator("img.icon").evaluateAll((nodes) =>
    nodes.map((n) => ({
      loaded: (n as HTMLImageElement).naturalWidth > 0,
      natural: (n as HTMLImageElement).naturalWidth,
      width: n.getBoundingClientRect().width,
    })),
  );
  expect(
    assets.every((a) => a.loaded && Math.abs(a.natural - a.width) < 1),
  ).toBeTruthy();
  await page.screenshot({ path: "test-results/manager-quote.png" });
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await page.screenshot({ path: "test-results/manager-confirm.png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("manager price publication, readonly inherited directories and real output task progress", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "价格维护", exact: true }).click();
  await page.getByLabel("商品1sale").fill("21");
  await page.getByRole("button", { name: "发布新版本" }).click();
  await page.getByRole("button", { name: "确认发布" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发布新版本", exact: true })).toBeEnabled();
  await expect(page.getByRole("status")).toHaveCount(0);
  await expect(page.locator(".alert, .feedback-wrap")).toHaveCount(0);
  await page.getByRole("button", { name: "报价工作台", exact: true }).click();
  await add(page);
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await page.getByRole("button", { name: "导出报价", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true }).first()).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(page.getByLabel("报价表保存位置")).not.toHaveAttribute(
    "readonly",
    "",
  );
  await expect(page.getByLabel("备份位置")).toHaveAttribute("readonly", "");
});

test("confirmed write with failed detail refresh clears the original draft and never offers a duplicate submit", async ({
  page,
}) => {
  await login(page);
  await add(page);
  await page.getByLabel("订单号", { exact: true }).fill("saved-refresh-failed");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  let refused = false;
  await page.route(host + "/action", async (route) => {
    const action = route.request().postDataJSON();
    if (action.action === "order" && !refused) {
      refused = true;
      await route.fulfill({
        json: {
          error: {
            status: 503,
            code: "SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED",
          },
        },
        headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:29346" },
      });
    } else await route.continue();
  });
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "订单已保存。但视图刷新失败",
  );
  await page.getByRole("button", { name: "报价工作台", exact: true }).click();
  await expect(page.getByLabel("订单号", { exact: true })).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "计算报价", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "订单记录", exact: true }).click();
  await expect(
    page.getByText("saved-refresh-failed", { exact: true }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "查看详情" }).first().click();
  await page.route(host + "/action", async (route) => {
    if (route.request().postDataJSON().action === "note")
      await route.fulfill({
        json: { error: { status: 409, code: "ORDER_REVISION_CHANGED" } },
        headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:29346" },
      });
    else await route.fallback();
  });
  await page.getByRole("button", { name: "追加备注", exact: true }).click();
  await page.getByLabel("备注内容").fill("失败后保留的备注草稿");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByLabel("备注内容")).toHaveValue("失败后保留的备注草稿");
});

test("development keeps an explicit connection editor without exposing it as formal authentication", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await page.getByRole("button", { name: "开发连接设置", exact: true }).click();
  await expect(page.getByLabel("服务地址", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toBeVisible();
});
