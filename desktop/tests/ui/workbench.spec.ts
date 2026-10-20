import { test, expect } from "@playwright/test";
import { connectDevelopment, selectDevelopmentIdentity } from "../development-connection.mjs";
const host = "http://127.0.0.1:18777";
let fixture: {
  connection: Record<string, string>;
  username: string;
  password: string;
  profile: string;
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
  await connectDevelopment(page, fixture, username);
  await page.evaluate(root=>(window as any).__TAURI_INTERNALS__.invoke("desktop_action",{request:{action:"save_output_root",root}}),fixture.profile+"/exports");
  await expect(
    page.getByRole("button", { name: "添加商品", exact: false }),
  ).toBeEnabled();
}
async function add(
  page: import("@playwright/test").Page,
  product = "安装服务",
) {
  await page.getByRole("button", { name: "添加商品", exact: false }).click();
  await page.getByLabel("第1行商品", { exact: true }).selectOption(product);
}
test("native development sign-in sequence retains the connection across logout and isolates the next actor", async ({ page }) => {
  await login(page);
  await add(page);
  await page.getByLabel("订单号", { exact: true }).fill("native-actor-switch");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await page.getByRole("button", { name: "核对并提交订单" }).click();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByRole("button", { name: "追加备注", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "账户菜单", exact: true }).click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByLabel("服务地址", { exact: true })).toHaveValue(fixture.connection.url);
  await page.getByText("证书与指纹（高级）", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: /^服务证书（PEM）/ })).toHaveValue(fixture.connection.certificate_pem);
  await expect(page.getByLabel("证书 SHA-256 指纹", { exact: true })).toHaveValue(fixture.connection.certificate_sha256);
  await page.getByText("证书与指纹（高级）", { exact: true }).click();
  await selectDevelopmentIdentity(page, fixture, "sales-one");
  await expect(page.getByLabel("账号", { exact: true })).toHaveCount(0);
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.getByRole("button", { name: "连接后台", exact: true }).click();
  await page.getByRole("button", { name: "我的订单", exact: true }).click();
  await expect(page.getByRole("button", { name: "查看详情" }).first()).toBeVisible();
  await expect(page.getByText("native-actor-switch", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "利润分析", exact: true })).toHaveCount(0);
});
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
  await expect(page.getByLabel("导出文件保存位置")).toHaveAttribute(
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
  await expect(page.getByRole("dialog")).toHaveCount(0);
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
  await login(page);
  await page.evaluate(
    (lines) =>
      sessionStorage.setItem(
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
  expect(box!.height).toBe(page.viewportSize()!.height - box!.y - 24);
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
  await expect(page.getByRole("button", { name: "核对并提交订单", exact: true })).toBeFocused();
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
  await expect(page.locator(".order-detail")).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "导出记录", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true }).first()).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(page.getByLabel("导出文件保存位置")).toHaveAttribute(
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
    page.getByRole("table", { name: "全部订单", exact: true }).getByText("saved-refresh-failed", { exact: true }),
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
    page.getByRole("button", { name: "验证并连接", exact: true }),
  ).toBeVisible();
});

test("price editor keeps final manual sale separate from cost markup and persists automatic mode", async ({ page }, info) => {
  await login(page);
  await page.getByRole("button", { name: "价格维护", exact: true }).click();
  await page.getByLabel("商品1product_id", { exact: true }).fill("KT板");
  await page.getByLabel("商品1cost", { exact: true }).fill("11.5");
  await page.getByLabel("商品1k", { exact: true }).fill("2");
  const automatic = page.getByLabel("商品1按成本乘K定价", { exact: true });
  const sale = page.getByLabel("商品1sale", { exact: true });
  await sale.fill("25");
  await automatic.check();
  await expect(sale).toHaveValue("23");
  await expect(sale).toHaveAttribute("readonly", "");
  await automatic.uncheck();
  await expect(sale).toHaveValue("25");
  await automatic.check();
  await expect(sale).toHaveValue("23");
  await page.getByLabel("商品1cost", { exact: true }).fill("0.335");
  await page.getByLabel("商品1k", { exact: true }).fill("3");
  await expect(sale).toHaveValue("1.005");
  await page.getByLabel("商品1cost", { exact: true }).fill("bad");
  await expect(page.getByText("请检查成本单价与K。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "发布新版本", exact: true })).toBeDisabled();
  await page.getByLabel("商品1cost", { exact: true }).fill("11.5");
  await page.getByLabel("商品1k", { exact: true }).fill("2");
  await expect(sale).toHaveValue("23");
  const withinCells = await page.locator(".price-editor td .input, .price-editor td select").evaluateAll(elements => elements.every(e => {
    const box=e.getBoundingClientRect(), cell=e.closest("td")!.getBoundingClientRect();
    return box.left>=cell.left && box.right<=cell.right;
  }));
  expect(withinCells).toBe(true);
  await page.screenshot({ path: info.outputPath("prices-auto-right.png"), fullPage: true });
  await expect(page.getByRole("columnheader", { name: "商品与成本", exact: true })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "销售定价", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "添加商品", exact: false }).click();
  const addedName = page.getByLabel("商品4product_id", { exact: true });
  await expect(addedName).toBeFocused();
  await expect(page.getByRole("button", { name: "发布新版本", exact: true })).toBeDisabled();
  await page.screenshot({ path: info.outputPath("prices-added.png"), fullPage: true });
  await page.getByRole("button", { name: "移除商品4", exact: true }).click();
  await expect(addedName).toHaveCount(0);
  const publish = async () => {
    await page.getByRole("button", { name: "发布新版本", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "发布新价格" });
    await expect(dialog).toContainText("确认发布这 3 种商品的定价？");
    const bounds = await dialog.boundingBox();
    expect(bounds?.width).toBe(380);
    expect(bounds?.height).toBe(194);
    await page.screenshot({ path: info.outputPath("prices-confirm.png"), fullPage: true });
    await page.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(page.getByRole("button", { name: "发布新版本", exact: true })).toBeEnabled();
  };
  await publish();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(automatic).toBeChecked();
  await expect(sale).toHaveValue("23");
  await automatic.uncheck();
  await expect(sale).toBeEditable();
  await expect(sale).toHaveValue("23");
  await sale.fill("20");
  await page.getByLabel("商品1k", { exact: true }).fill("3");
  await expect(sale).toHaveValue("20");
  await publish();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(automatic).not.toBeChecked();
  await expect(sale).toHaveValue("20");
  await page.screenshot({ path: info.outputPath("prices-manual-right.png"), fullPage: true });
  for (const width of [1440, 1100, 720, 640]) {
    await page.setViewportSize({ width, height: 884 });
    const geometry = await page.evaluate(() => {
      const table = document.querySelector<HTMLTableElement>(".price-editor")!;
      const header = table.tHead!.rows[1];
      const row = table.tBodies[0].rows[0];
      const right = (e: Element) => e.getBoundingClientRect().right - parseFloat(getComputedStyle(e).paddingRight);
      return {
        documentOverflow: document.documentElement.scrollWidth - innerWidth,
        rowHeight: row.getBoundingClientRect().height,
        headerFont: getComputedStyle(header.cells[2]).fontFamily,
        groupEdge: table.tHead!.rows[0].cells[1].getBoundingClientRect().left,
        saleEdge: row.cells[4].getBoundingClientRect().left,
        numericAlignment: [2, 3].map(i => Math.abs(right(header.cells[i]) - right(row.cells[i].querySelector("input")!))),
        controlsContained: Array.from(table.querySelectorAll("td input, td select, td button")).every(e => {
          const box = e.getBoundingClientRect(), cell = e.closest("td")!.getBoundingClientRect();
          return box.left >= cell.left && box.right <= cell.right;
        }),
        iconsCorrect: Array.from(table.querySelectorAll<HTMLImageElement>(".icon")).every(e => {
          const size = e.closest(".price-kind-icon") ? 14 : 16;
          const expected = e.closest(".price-kind-icon") ? "price-chevron.svg" : "price-trash.svg";
          const box = e.getBoundingClientRect();
          return e.complete && e.naturalWidth === 20 && e.naturalHeight === 20 && e.src.endsWith(expected) && Math.abs(box.width - size) < 0.1 && Math.abs(box.height - size) < 0.1;
        }),
      };
    });
    expect(geometry.documentOverflow).toBeLessThanOrEqual(1);
    expect(geometry.rowHeight).toBe(80);
    expect(geometry.headerFont).toContain("Noto Sans SC");
    expect(Math.abs(geometry.groupEdge - geometry.saleEdge)).toBeLessThanOrEqual(1);
    expect(geometry.numericAlignment.every(error => error <= 1)).toBe(true);
    expect(geometry.controlsContained).toBe(true);
    expect(geometry.iconsCorrect).toBe(true);
    await page.screenshot({ path: info.outputPath(`prices-layout-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 640, height: 884 });
  await page.getByLabel("商品1k", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(sale).toBeFocused();
  const scroller = page.getByRole("region", { name: "价格目录" });
  const visible = await sale.evaluate(e => {
    const box = e.getBoundingClientRect(), region = e.closest(".price-table-scroll")!.getBoundingClientRect();
    return box.left >= region.left && box.right <= region.right;
  });
  expect(visible).toBe(true);
  await page.keyboard.press("Tab");
  await expect(automatic).toBeFocused();
  await page.keyboard.press("Space");
  await expect(automatic).toBeChecked();
  await expect(sale).toHaveValue("34.5");
  await page.keyboard.press("Space");
  await expect(sale).toHaveValue("20");
  await scroller.evaluate(e => e.scrollLeft = 0);
  await page.setViewportSize({ width: 1440, height: 884 });
  await page.getByRole("button", { name: "报价工作台", exact: true }).click();
  await add(page, "KT板");
  await page.getByLabel("第1行高", { exact: true }).fill("1");
  await page.getByLabel("第1行宽", { exact: true }).fill("1");
  await page.getByRole("button", { name: "计算报价", exact: true }).click();
  await expect(page.locator(".amount strong")).toHaveText("20.00");
  await expect(page.locator(".finance-cost b")).toHaveText("11.50");
  await expect(page.locator(".profit-pair strong").first()).toHaveText("8.50");
});

for (const username of ["manager", "sales-one"]) {
  test(`${username} direct add, inline product changes and shared column alignment`, async ({ page }, info) => {
    await login(page, username);
    await page.getByLabel("客户 / 淘宝 ID", { exact: true }).fill("保持客户");
    await page.getByRole("button", { name: "添加商品", exact: false }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const product = page.getByLabel("第1行商品", { exact: true });
    await expect(product).toHaveValue("户外写真");
    await page.getByLabel("第1行高", { exact: true }).fill("2");
    await page.getByLabel("第1行宽", { exact: true }).fill("3");
    await page.getByLabel("第1行数量", { exact: true }).fill("4");
    await page.getByRole("button", { name: "计算报价", exact: true }).click();
    await expect(page.locator(".amount strong")).toHaveText("480.00");
    await product.selectOption("安装服务");
    await expect(page.getByLabel("第1行高", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "核对并提交订单", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "计算报价", exact: true }).click();
    await expect(page.locator(".amount strong")).toHaveText("400.00");
    await product.selectOption("PVC 硬板");
    await expect(page.getByLabel("第1行高", { exact: true })).toHaveValue("2");
    await expect(page.getByLabel("第1行宽", { exact: true })).toHaveValue("3");
    await expect(page.getByLabel("第1行数量", { exact: true })).toHaveValue("4");
    await expect(page.getByLabel("客户 / 淘宝 ID", { exact: true })).toHaveValue("保持客户");
    for (const width of [1440, 1364]) {
      await page.setViewportSize({ width, height: 974 });
      const errors = await page.evaluate(() => {
        const header = document.querySelector(".table-head")!;
        const row = document.querySelector(".quote-row:not(.table-head)")!;
        const head = (index: number) => header.children[index] as HTMLElement;
        const right = (e: HTMLElement) => e.getBoundingClientRect().right - parseFloat(getComputedStyle(e).paddingRight) - parseFloat(getComputedStyle(e).borderRightWidth);
        const center = (e: Element) => { const b = e.getBoundingClientRect(); return b.x + b.width / 2; };
        return [
          Math.abs(head(1).getBoundingClientRect().left + 8 - row.querySelector("select")!.getBoundingClientRect().left),
          Math.abs(center(head(2)) - center(row.querySelector(".dimensions")!)),
          Math.abs(right(head(3)) - right(row.querySelector(".quantity")!)),
          Math.abs(right(head(4)) - right(row.querySelector(".line-amount")!)),
        ];
      });
      expect(errors.every(error => error <= 2)).toBe(true);
      expect(await page.locator(".line-scroll").evaluate(e => e.scrollWidth <= e.clientWidth + 1)).toBe(true);
      await page.screenshot({ path: info.outputPath(`quote-columns-${width}.png`), fullPage: true });
    }
  });
}

test("P07-07 customer match edits the chosen order and exports period financial report", async ({page})=>{
  await login(page);
  await page.getByLabel("订单号",{exact:true}).fill("00000");
  await page.getByLabel("客户 / 淘宝 ID",{exact:true}).fill("客户0");
  const match=page.getByRole("region",{name:"匹配客户与订单"});
  await expect(match.getByRole("button",{name:"继续编辑",exact:true})).toBeVisible();
  await page.screenshot({path:"test-results/p07-07-customer-match.png"});
  await match.getByRole("button",{name:"继续编辑",exact:true}).click();
  await expect(page.getByText("已保存版本 1",{exact:true})).toBeVisible();
  await page.getByLabel("第1行数量",{exact:true}).fill("2");
  await page.getByRole("button",{name:"查看修改记录",exact:true}).click();
  await page.getByRole("button",{name:"继续编辑",exact:true}).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("第1行数量",{exact:true})).toHaveValue("2");
  await page.getByRole("button",{name:"计算报价",exact:true}).click();
  await page.getByRole("button",{name:"保存修改",exact:true}).click();
  await page.getByRole("button",{name:"确认提交",exact:true}).click();
  await expect(page.getByRole("button",{name:/^修改记录（/})).toBeVisible();
  await page.getByRole("button",{name:"继续编辑",exact:true}).click();
  await expect(page.getByText("已保存版本 2",{exact:true})).toBeVisible();
  await page.getByLabel("第1行数量",{exact:true}).fill("3");
  await page.getByRole("button",{name:"查看修改记录",exact:true}).click();
  await page.getByRole("button",{name:"继续编辑",exact:true}).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("第1行数量",{exact:true})).toHaveValue("3");
  await page.getByRole("button",{name:"计算报价",exact:true}).click();
  await page.getByRole("button",{name:"保存修改",exact:true}).click();
  await page.getByRole("button",{name:"确认提交",exact:true}).click();
  await page.getByRole("button",{name:/^修改记录（/}).click();
  await expect(page.locator("summary").filter({hasText:"版本 2 → 3"})).toBeVisible();
  await page.locator("summary").filter({hasText:"版本 2 → 3"}).click();
  const diff=page.locator(".revision-diff[open]");
  await expect(diff.getByRole("columnheader",{name:"修改前",exact:true})).toBeVisible();
  const quantity=diff.getByRole("row").filter({hasText:"第 1 项 · 数量"});
  await expect(quantity.getByRole("cell").nth(1)).toHaveText("2");
  await expect(quantity.getByRole("cell").nth(2)).toHaveText("3");
  await page.screenshot({path:"test-results/p07-07-edited-order.png"});
  await page.keyboard.press("Escape");
  await page.getByRole("button",{name:"订单记录",exact:true}).click();
  await page.getByRole("button",{name:"按客户查看",exact:true}).click();
  await page.getByLabel("搜索客户",{exact:true}).fill("客户0");
  await page.getByRole("button",{name:"查找",exact:true}).click();
  await expect(page.locator(".customer-group")).toHaveCount(1);
  await page.screenshot({path:"test-results/p07-07-customer-group.png"});
  await page.getByRole("button",{name:"导出记录",exact:true}).click();
  await page.getByRole("button",{name:"导出 Excel",exact:true}).click();
  await expect(page.getByRole("button",{name:"打开文件夹",exact:true})).toBeVisible();
  await expect(page.getByText("内部财务报表（期间）",{exact:true})).toBeVisible();
  await page.screenshot({path:"test-results/p07-07-report-folder.png"});
});

test("P07-07 continue existing draft from another order preserves pending edits",async({page})=>{
  await login(page);
  await page.getByLabel("订单号",{exact:true}).fill("00000");
  await page.getByLabel("客户 / 淘宝 ID",{exact:true}).fill("客户0");
  await page.getByRole("region",{name:"匹配客户与订单"}).getByRole("button",{name:"继续编辑",exact:true}).click();
  await page.getByLabel("第1行数量",{exact:true}).fill("4");
  const readOther=async()=>{
    await page.getByRole("button",{name:"订单记录",exact:true}).click();
    await page.getByLabel("搜索订单",{exact:true}).fill("00001");
    await page.getByRole("button",{name:"筛选",exact:true}).click();
    const otherOrder = page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "00001", exact: true }),
    });
    await expect(otherOrder).toHaveCount(1);
    await otherOrder.getByRole("button",{name:"查看详情",exact:true}).click();
    await page.getByRole("button",{name:"继续编辑",exact:true}).click();
  };
  await readOther();
  const dialog=page.getByRole("dialog",{name:"尚有未保存的修改"});
  await dialog.getByRole("button",{name:"继续编辑",exact:true}).click();
  await expect(page.getByLabel("订单号",{exact:true})).toHaveValue("00000");
  await expect(page.getByLabel("第1行数量",{exact:true})).toHaveValue("4");
  await readOther();
  await dialog.getByRole("button",{name:"放弃修改",exact:true}).click();
  await expect(page.getByLabel("订单号",{exact:true})).toHaveValue("00001");
  await expect(page.getByLabel("第1行数量",{exact:true})).toHaveValue("1");
});

// Presentation-only fixture: the server's real 105-part creation, pagination,
// permissions and immutable retry are covered in report_exports Rust tests.
test("P07-07 report parts can page, retry one file and locate its folder", async ({page})=>{
  await login(page);
  let retried=false;const folders:string[]=[];const retryIds:string[]=[];
  const id=(part:number)=>`00000000-0000-4000-8000-${String(part).padStart(12,"0")}`;
  await page.route(host+"/action",async route=>{
    const data=route.request().postDataJSON();
    if(data.action==="outputs") {
      const offset=data.offset??0;
      const jobs=Array.from({length:Math.min(100,105-offset)},(_,i)=>{const part=offset+i+1;return {job_id:id(part),order_id:id(1),kind:"excel_period",state:part===101&&!retried?"failed":"done",error:part===101&&!retried?"生成失败":null,created_at:"2026-10-17T13:00:00Z",range:{from:"2026-01-01",to:"2026-10-31"},batch:{id:id(1),part,count:105,from:"2026-10-01",to:"2026-10-31",order_count:25}};});
      await route.fulfill({json:{ok:{jobs,offset,total:105,limit:100}}});return;
    }
    if(data.action==="retry_output"){retryIds.push(data.job_id);retried=true;await route.fulfill({json:{ok:{}}});return;}
    if(data.action==="open_output_folder"){folders.push(data.job_id);await route.fulfill({json:{ok:{}}});return;}
    await route.continue();
  });
  await page.getByRole("button",{name:"导出记录",exact:true}).click();
  await expect(page.getByRole("heading",{name:"导出记录 共 105 项",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"下一页",exact:true}).click();
  await expect(page.getByText("第 2 / 2 页",{exact:true})).toBeVisible();
  const part=page.getByRole("row").filter({hasText:"第 101 / 105 份"});
  await expect(part.getByRole("button",{name:"打开文件夹"})).toHaveCount(0);
  await part.getByRole("button",{name:"重新导出",exact:true}).click();
  await expect(page.getByText("第 2 / 2 页",{exact:true})).toBeVisible();
  await part.getByRole("button",{name:"打开文件夹",exact:true}).click();
  expect(retryIds).toEqual([id(101)]);expect(folders).toEqual([id(101)]);
  await expect(page.getByRole("button",{name:"下一页",exact:true})).toBeDisabled();
  await page.screenshot({path:"test-results/p07-07-report-parts.png"});
});

test('discount participation persists and pointer reordering changes the saved order',async({page},info)=>{
  await login(page);
  await page.getByRole('button',{name:'价格维护',exact:true}).click();
  await page.getByLabel('商品3参与折扣',{exact:true}).uncheck();
  await page.getByRole('button',{name:'发布新版本',exact:true}).click();
  await page.getByRole('button',{name:'确认发布',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByLabel('商品3参与折扣',{exact:true})).not.toBeChecked();
  await page.getByRole('button',{name:'报价工作台',exact:true}).click();
  await add(page,'户外写真');
  await page.getByLabel('第1行高',{exact:true}).fill('2');
  await page.getByLabel('第1行宽',{exact:true}).fill('5');
  await page.getByRole('button',{name:'添加商品',exact:false}).click();
  await page.getByLabel('第2行商品',{exact:true}).selectOption('安装服务');
  await page.getByRole('button',{name:'添加折扣',exact:false}).click();
  await page.getByLabel('第3行折扣',{exact:true}).fill('50%');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.locator('.amount strong')).toHaveText('200.00');
  await expect(page.locator('.quote-table')).not.toContainText('销售单价');
  await expect(page.locator('.quote-table')).not.toContainText('顺序折扣');
  await expect(page.locator('.quote-table .k-value')).toHaveCount(0);
  const from=await page.getByRole('button',{name:'移动第3行',exact:true}).boundingBox();
  const to=await page.getByRole('button',{name:'移动第1行',exact:true}).boundingBox();
  await page.mouse.move(from!.x+10,from!.y+15);await page.mouse.down();
  await page.mouse.move(to!.x+10,to!.y+15,{steps:10});await page.mouse.up();
  await expect(page.getByLabel('第1行折扣',{exact:true})).toHaveValue('50%');
  await expect(page.getByRole('button',{name:'核对并提交订单',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.locator('.amount strong')).toHaveText('300.00');
  await page.getByRole('button',{name:'移动第1行',exact:true}).focus();await page.keyboard.press('ArrowDown');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.locator('.amount strong')).toHaveText('200.00');
  await page.screenshot({path:info.outputPath('discount-reorder.png'),fullPage:true});
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'继续编辑',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'继续编辑',exact:true}).click();
  await expect(page.getByLabel('第2行折扣',{exact:true})).toHaveValue('50%');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.locator('.amount strong')).toHaveText('200.00');
});

test('customer rejection opens an actionable picker and preserves the confirmed price',async({page},info)=>{
  await login(page);await add(page);
  await page.getByLabel('客户 / 淘宝 ID',{exact:true}).fill('测试匹配客户');
  await page.getByLabel('订单号',{exact:true}).fill('original-buyer-order');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'追加备注',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'报价工作台',exact:true}).click();
  await add(page);
  await page.getByLabel('客户 / 淘宝 ID',{exact:true}).fill('测试匹配客户');
  await page.getByLabel('订单号',{exact:true}).fill('another-order-for-buyer');
  await expect(page.getByRole('region',{name:'匹配客户与订单'}).getByRole('button',{name:'该客户新建订单',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'是否是这个客户',exact:true});
  await expect(picker).toBeVisible();
  await expect(picker.getByRole('button',{name:'该客户新建订单',exact:true})).toBeVisible();
  for(const width of [1440,720]){
    await page.setViewportSize({width,height:884});
    await expect(picker.getByRole('button',{name:'继续编辑',exact:true})).toBeVisible();
    expect(await picker.locator('.customer-match').evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);
    await page.screenshot({path:info.outputPath(`customer-selection-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:884});
  await picker.getByRole('button',{name:'该客户新建订单',exact:true}).click();
  await expect(picker).toHaveCount(0);
  await expect(page.locator('.amount strong')).toHaveText('100.00');
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'追加备注',exact:true})).toBeVisible();
});

test('lost native calculation exposes recalculation without changing any dimensions',async({page})=>{
  await login(page);await add(page);
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  let injected=false;
  await page.route('**/action',async route=>{
    if(route.request().postDataJSON()?.action==='save_order'&&!injected){injected=true;return route.fulfill({json:{error:{code:'CALCULATION_REQUIRED',status:409}}});}
    await route.continue();
  });
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'提交未完成',exact:true})).toBeVisible();
  await page.getByRole('dialog',{name:'提交未完成',exact:true}).getByRole('button',{name:'重新核价',exact:true}).click();
  await expect(page.locator('.amount strong')).toHaveText('100.00');
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'追加备注',exact:true})).toBeVisible();
});
