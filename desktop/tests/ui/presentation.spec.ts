// Presentation-only native IPC stand-in; real service and financial gates remain separate.
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import { inspectPresentation } from "../native-presentation.mjs";
const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (e) => errors.push(e.message));
});
test.afterEach(async ({ page }) => {
  expect(pageErrors.get(page)).toEqual([]);
  await expect(page.locator(".alert, .feedback-wrap")).toHaveCount(0);
});

async function bootstrap(
  page: Page,
  delivery = "manager",
  failure = false,
  chartCase = "mixed",
) {
  await page.addInitScript(
    ({ delivery, failure, chartCase }) => {
      let attempts = 0;
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
          invoke: async (
            command: string,
            { request }: { request: { action: string } },
          ) => {
            if (command !== "desktop_action") return 0;
            const role = delivery === "manager" ? "admin" : "sales";
            (window as any).__businessRequests ??= [];
            (window as any).__businessRequests.push(request);
            switch (request.action) {
              case "connection":
                return {
                  delivery,
                  automatic: true,
                  connection: null,
                  pending: false,
                };
              case "bootstrap":
                if (failure && attempts++ === 0)
                  throw { status: 401, code: "DEVICE_NOT_AUTHORIZED" };
                return {
                  delivery,
                  automatic: true,
                  session: {
                    role,
                    username: "中文测试账户".repeat(20),
                    subject: "synthetic",
                    pending: false,
                  },
                };
              case "business_directory": return {directory:"",ledger_id:"00000000-0000-4000-8000-000000000001",applied:false};
              case "prices":
                return {
                  price_version_id: "presentation-v1",
                  pricing_mode_version: "final-unit-v1",
                  items: [
                    {
                      product_id: "单件",
                      single: true,
                      sale: "10",
                      k: "1",
                      ...(role === "admin" ? { cost: "4" } : {}),
                    },
                  ],
                };
              case "settings":
                return {
                  revision: "1",
                  export_dir: chartCase === "managed-locations" ? "\\\\192.168.4.23\\共享\\报价表" : "\\\\localhost\\中文共享\\报价表",
                  image_dir: chartCase === "managed-locations" ? "\\\\192.168.4.23\\共享\\报价图片" : "\\\\localhost\\中文共享\\报价图片",
                };
              case "backup_status":
                return {
                  delivery_complete: true,
                  target: chartCase === "managed-locations" ? "\\\\192.168.4.23\\共享\\backup" : "synthetic",
                  last_success: { created_at: "2026-10-15T12:34:56Z" },
                  last_error: null,
                };
              case "pick_directory":
                return {
                  directory:
                    (request as any).target === "export_dir"
                      ? chartCase === "managed-locations" ? "\\\\192.168.4.23\\共享\\新报价表" : "\\\\localhost\\中文共享\\新报价表"
                      : null,
                };
              case "save_settings":
                return {
                  revision: "2",
                  export_dir: (request as any).export_dir,
                  image_dir: (request as any).image_dir,
                };
              case "outputs":
                return { jobs: [] };
              case "analytics": {
                const analysis = {
                  format: "777-profit-analysis-v1",
                  ...(request as any),
                  timezone: "Asia/Shanghai",
                  week_starts_on: "Monday",
                  ledger_revision: "31",
                  unplaced_date_orders: 0,
                  totals: {
                    order_count: 25,
                    income_cents: "10000",
                    cost_cents: "8500",
                    profit_cents: "1500",
                    margin: "15.0%",
                  },
                  buckets: [
                    {
                      start: (request as any).from.slice(0, 10),
                      ...(chartCase === "legacy"
                        ? {}
                        : {
                            profit_ohlc: {
                              open_cents: "0",
                              high_cents: "500",
                              low_cents: "-1200",
                              close_cents: "-1000",
                            },
                          }),
                      totals: {
                        order_count: 12,
                        income_cents: "6000",
                        cost_cents: "7000",
                        profit_cents: "-1000",
                        margin: "-16.7%",
                      },
                    },
                    {
                      start: (request as any).to.slice(0, 10),
                      ...(chartCase === "legacy"
                        ? {}
                        : {
                            profit_ohlc: {
                              open_cents: "-1000",
                              high_cents: "2000",
                              low_cents: "-1300",
                              close_cents: "1500",
                            },
                          }),
                      totals: {
                        order_count: 13,
                        income_cents: "4000",
                        cost_cents: "1500",
                        profit_cents: "2500",
                        margin: "62.5%",
                      },
                    },
                  ],
                };
                if (chartCase === "zero") {
                  analysis.totals = {
                    order_count: 25,
                    income_cents: "0",
                    cost_cents: "0",
                    profit_cents: "0",
                    margin: null,
                  } as any;
                  for (const b of analysis.buckets) {
                    b.totals = {
                      ...b.totals,
                      income_cents: "0",
                      cost_cents: "0",
                      profit_cents: "0",
                      margin: null,
                    } as any;
                    b.profit_ohlc = {
                      open_cents: "0",
                      high_cents: "0",
                      low_cents: "0",
                      close_cents: "0",
                    };
                  }
                }
                return analysis;
              }
              default:
                throw { status: 400, code: "UNEXPECTED_PRESENTATION_REQUEST" };
            }
          },
        },
      });
      localStorage.setItem(
        "777-desktop-draft-v1",
        JSON.stringify({
          schema: "777-desktop-draft-v1",
          details: {
            customer: "中文长客户名称".repeat(20),
            order_ref: "长订单号".repeat(20),
            wechat: "中文微信".repeat(20),
          },
          lines: Array.from({ length: 30 }, (_, i) => ({
            id: "row" + i,
            raw: {
              line_kind: "normal",
              product_id: "单件",
              q: "1",
              h: "",
              w: "",
              name: "",
            },
          })),
        }),
      );
    },
    { delivery, failure, chartCase },
  );
  await page.goto("/");
}

for (const delivery of ["manager", "sales"]) {
  test(`${delivery} local fonts, original icons and compact layout at four emulated scales`, async ({
    page,
  }, info) => {
    await bootstrap(page, delivery);
    await expect(
      page.getByRole("button", { name: "添加商品", exact: false }),
    ).toBeEnabled();
    const output = info.outputPath("presentation");
    fs.mkdirSync(output, { recursive: true });
    const result = await inspectPresentation(page, output, delivery);
    expect(result.samples).toHaveLength(4);
    expect(result.samples.every((s) => s.table_scrollable)).toBeTruthy();
    for (const label of ["服务地址", "服务证书（PEM）", "账号", "密码"])
      await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
    const region = page.getByRole("region", { name: "商品明细滚动区" });
    await region.focus();
    await region.press("End");
    await expect
      .poll(() => region.evaluate((e) => e.scrollTop))
      .toBeGreaterThan(0);
    await page.getByRole("button", { name: "存储与备份", exact: true }).click();
    const path = page.getByLabel("报价图片保存位置");
    await expect(path).toHaveValue(/中文共享/);
    await expect(path).toHaveAttribute("title", /中文共享/);
    if (delivery === "sales")
      await expect(path).toHaveAttribute("readonly", "");
  });
  test(`${delivery} failed automatic entry retries without technical/login controls`, async ({
    page,
  }) => {
    await page.clock.install();
    await bootstrap(page, delivery, true);
    await expect(
      page.locator(".formal-idle"),
    ).toBeVisible();
    for (const label of ["服务地址", "服务证书（PEM）", "账号", "密码"])
      await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", {name:"重新连接",exact:true})).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await page.clock.fastForward(16000);
    await expect(
      page.getByRole("button", { name: "添加商品", exact: false }),
    ).toBeEnabled();
  });
}

test("keyboard dialog returns focus and fonts fall back without a banner", async ({
  page,
}) => {
  await page.route("**/fonts/*", (route) => route.abort());
  await page.route("**/icons/74181.svg", (route) => route.abort());
  await bootstrap(page);
  await expect(
    page.getByText("字体资源加载失败，当前使用系统字体。", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("img", { name: "图标不可用" })).toHaveCount(0);
  const add = page.getByRole("button", { name: "添加商品", exact: false });
  await add.focus();
  await add.press("Enter");
  await expect(page.getByLabel("第31行商品", { exact: true })).toHaveValue("单件");
  await expect(page.getByLabel("第31行商品", { exact: true })).toBeFocused();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("manager directory selection is a draft until published and cancellation preserves the path", async ({
  page,
}) => {
  await bootstrap(page);
  await page.getByRole("button", { name: "刷新价格", exact: true }).click();
  await expect(
    page.getByText("价格已刷新，请重新计算并核对。", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await page
    .getByRole("button", { name: "选择报价表保存文件夹", exact: true })
    .click();
  await expect(page.getByLabel("报价表保存位置", { exact: true })).toHaveValue(
    "\\\\localhost\\中文共享\\新报价表",
  );
  await page
    .getByRole("button", { name: "选择报价图片保存文件夹", exact: true })
    .click();
  await expect(
    page.getByLabel("报价图片保存位置", { exact: true }),
  ).toHaveValue("\\\\localhost\\中文共享\\报价图片");
  expect(
    await page.evaluate(
      () =>
        (window as any).__businessRequests.filter(
          (r: any) => r.action === "save_settings",
        ).length,
    ),
  ).toBe(0);
  await expect(page.getByText("[object Object]", { exact: false })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("状态：备份正常", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "发布保存位置", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as any).__businessRequests.filter(
            (r: any) => r.action === "save_settings",
          ).length,
      ),
    )
    .toBe(1);
});

test("sales inherits readonly directories and sees only its export explanation", async ({
  page,
}) => {
  await bootstrap(page, "sales");
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  await expect(
    page.getByLabel("报价表保存位置", { exact: true }),
  ).toHaveAttribute("readonly", "");
  await expect(page.getByRole("button", { name: /选择.*文件夹/ })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "利润分析", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "导出记录", exact: true }).click();
  await expect(page.getByText("内部财务报表", { exact: false })).toHaveCount(0);
  await expect(page.getByText("暂无导出记录", { exact: false })).toBeVisible();
});

test("profit shows aggregate bars rather than orders and switches calendar periods", async ({
  page,
}, info) => {
  await page.addInitScript(() => {
    Date.now = () => Date.parse("2026-10-15T06:41:10.123Z");
  });
  await bootstrap(page);
  await page.getByRole("button", { name: "利润分析", exact: true }).click();
  await expect(
    page.getByText("有效订单 25 笔", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "收入成本利润柱状图" }),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /利润-10.00/ })).toBeVisible();
  await expect(page.getByText("总收入", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("客户、订单号或微信")).toHaveCount(0);
  const latest = () =>
    page.evaluate(() =>
      (window as any).__businessRequests
        .filter((r: any) => r.action === "analytics")
        .at(-1),
    );
  for (const [label, from, period] of [
    ["近1周", "2026-10-08T14:41:10.123", "day"],
    ["近1月", "2026-09-15T14:41:10.123", "day"],
    ["近1年", "2025-10-15T14:41:10.123", "month"],
    ["近1天", "2026-10-14T14:41:10.123", "day"],
  ]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(
      page.getByRole("button", { name: "查看汇总", exact: true }),
    ).toBeEnabled();
    expect(await latest()).toMatchObject({
      from,
      to: "2026-10-15T14:41:10.123",
      period,
    });
    await expect(
      page.getByRole("button", { name: label, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  }
  for (const period of ["week", "month", "year", "day"]) {
    await page.getByLabel("图表分组", { exact: true }).selectOption(period);
    await expect(
      page.getByRole("button", { name: "查看汇总", exact: true }),
    ).toBeEnabled();
    expect(await latest()).toMatchObject({
      period,
      from: "2026-10-14T14:41:10.123",
      to: "2026-10-15T14:41:10.123",
    });
  }
  await page.evaluate(() => {
    Date.now = () => Date.parse("2026-10-15T07:41:10.123Z");
  });
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看汇总", exact: true }),
  ).toBeEnabled();
  expect(await latest()).toMatchObject({
    from: "2026-10-14T15:41:10.123",
    to: "2026-10-15T15:41:10.123",
    period: "day",
  });
  await page.getByLabel("开始时间", { exact: true }).fill("2026-10-01T08:00");
  await page.getByLabel("结束时间", { exact: true }).fill("2026-10-02T09:00");
  await page.getByRole("button", { name: "查看汇总", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看汇总", exact: true }),
  ).toBeEnabled();
  const custom = await latest();
  expect(custom).toMatchObject({
    from: "2026-10-01T08:00:00.000",
    to: "2026-10-02T09:00:00.000",
    period: "day",
  });
  await expect(
    page.getByRole("button", { name: "近1天", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.evaluate(() => {
    Date.now = () => Date.parse("2026-10-16T07:41:10.123Z");
  });
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看汇总", exact: true }),
  ).toBeEnabled();
  expect(await latest()).toEqual(custom);
  expect(
    await page.evaluate(() =>
      (window as any).__businessRequests.some(
        (r: any) => r.action === "orders",
      ),
    ),
  ).toBe(false);
  await page.screenshot({
    path: info.outputPath("profit-wide.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 720, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("profit-narrow.png"),
    fullPage: true,
  });
});

test("four chart types share one snapshot and remain readable at wide and narrow widths", async ({
  page,
}, info) => {
  await bootstrap(page);
  await page.getByRole("button", { name: "利润分析", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "收入成本利润柱状图" }),
  ).toBeVisible();
  const requests = () =>
    page.evaluate(() =>
      (window as any).__businessRequests.filter(
        (r: any) => r.action === "analytics",
      ),
    );
  const before = await requests();
  for (const width of [1440, 720, 640]) {
    await page.setViewportSize({ width, height: 960 });
    for (const [name, region] of [
      ["柱状图", "收入成本利润柱状图"],
      ["折线图", "收入成本利润折线图"],
      ["饼图", "各期间盈亏占比饼图"],
      ["K线图", "累计利润K线图"],
    ]) {
      const button = page
        .getByRole("group", { name: "图表类型" })
        .getByRole("button", { name, exact: true });
      await button.focus();
      await button.press("Enter");
      await expect(button).toHaveAttribute("aria-pressed", "true");
      await expect(
        page.getByRole("region", { name: region, exact: true }),
      ).toBeVisible();
      expect(await requests()).toEqual(before);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(
        await page
          .locator("svg")
          .evaluateAll((elements) =>
            elements.every((e) => !/NaN|Infinity/.test(e.outerHTML)),
          ),
      ).toBe(true);
      if (name === "饼图") {
        await expect(
          page.getByRole("img", { name: /亏损-10.00元，占比28.6%/ }),
        ).toBeVisible();
        await expect(
          page.getByRole("img", { name: /盈利25.00元，占比71.4%/ }),
        ).toBeVisible();
      }
      if (name === "K线图") {
        await expect(
          page.getByRole("img", { name: /开0.00，高5.00，低-12.00，收-10.00/ }),
        ).toBeVisible();
        await page.getByText("查看K线数据", { exact: true }).click();
        await expect(
          page.getByRole("columnheader", { name: "收（元）" }),
        ).toBeVisible();
      }
      if (name !== "饼图") {
        await expect
          .poll(() =>
            page
              .getByRole("region", { name: region, exact: true })
              .evaluate(
                (element) =>
                  Number(element.querySelector("svg")?.getAttribute("width")) <=
                  element.clientWidth,
              ),
          )
          .toBe(true);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: info.outputPath(`chart-${width}-${name}.png`),
        fullPage: true,
      });
    }
  }
});

test("old service never fabricates candlesticks from aggregate totals", async ({
  page,
}) => {
  await bootstrap(page, "manager", false, "legacy");
  await page.getByRole("button", { name: "利润分析", exact: true }).click();
  await page.getByRole("button", { name: "K线图", exact: true }).click();
  await expect(
    page.getByText("当前服务未提供K线数据，请更新服务后刷新。", {
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.getByRole("region", { name: "累计利润K线图" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "折线图", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "收入成本利润折线图" }),
  ).toBeVisible();
});

test("zero-profit orders keep empty pie and flat candles finite", async ({
  page,
}) => {
  await bootstrap(page, "manager", false, "zero");
  await page.getByRole("button", { name: "利润分析", exact: true }).click();
  await page.getByRole("button", { name: "饼图", exact: true }).click();
  await expect(
    page.getByText("各期间净利润均为0，暂无占比。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "各期间盈亏占比饼图" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "K线图", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "累计利润K线图" }),
  ).toBeVisible();
  expect(
    await page
      .locator("svg")
      .evaluateAll((elements) =>
        elements.every((e) => !/NaN|Infinity/.test(e.outerHTML)),
      ),
  ).toBe(true);
  await expect(
    page.getByRole("img", { name: /开0.00，高0.00，低0.00，收0.00/ }),
  ).toHaveCount(2);
});

test("formal settings conceal managed addresses while preserving the actual saved directory", async ({ page }) => {
  await bootstrap(page, "manager", false, "managed-locations");
  await page.getByRole("button", { name: "存储与备份", exact: true }).click();
  const table = page.getByLabel("报价表保存位置", { exact: true });
  const image = page.getByLabel("报价图片保存位置", { exact: true });
  await expect(table).toHaveValue("已配置的报价表位置");
  await expect(image).toHaveValue("已配置的报价图片位置");
  await expect(table).toHaveAttribute("readonly", "");
  await expect(page.getByText("当前服务", { exact: true })).toHaveCount(0);
  await expect(page.locator(".settings")).not.toContainText("192.168.4.23");
  expect(await page.locator(".settings input").evaluateAll(nodes => nodes.every(n => {
    const field = n as HTMLInputElement;
    return ![field.value, field.title, field.getAttribute("aria-label") ?? ""].some(v => v.includes("192.168.4.23"));
  }))).toBe(true);
  await page.getByRole("button", { name: "选择报价表保存文件夹", exact: true }).click();
  await expect(table).toHaveValue("已配置的报价表位置");
  await page.getByRole("button", { name: "发布保存位置", exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__businessRequests.filter((r: any) => r.action === "save_settings").at(-1))).toMatchObject({
    export_dir: "\\\\192.168.4.23\\共享\\新报价表",
    image_dir: "\\\\192.168.4.23\\共享\\报价图片",
  });
  await expect(table).toHaveValue("已配置的报价表位置");
});
