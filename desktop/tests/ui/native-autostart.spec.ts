// Actual DetailPage markup and browser locators; this is not native IPC acceptance.
import { test, expect } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fs from "node:fs";
import { allowed, type Permission } from "../../src/state/permissions";
import { DetailPage } from "../../src/features/DetailPage";
import type { Workbench } from "../../src/state/useWorkbench";
import { recordAutomaticEntry } from "../windows-autostart.mjs";

function detail(busy: boolean, role = "admin") {
  const app = {
    busy, pending: false, session: { role }, can:(id:Permission)=>allowed(null,role,id),
    selected: { details: { customer: "isolated", order_ref: "native-idle", wechat: "" },
      state: "active", created_at: "2026-10-14T00:00:00Z", lines: [], notes: [],
      income_cents: "1000", cost_cents: "400", profit_cents: "600" },
  } as unknown as Workbench;
  return renderToStaticMarkup(createElement("main", { className: "workspace", "aria-busy": busy },
    createElement(DetailPage, { app })));
}

for (const delivery of ["manager", "sales"]) {
  test(`${delivery} native completion uses submitted DetailPage controls and records success last`, async ({ page }, testInfo) => {
    const output = testInfo.outputPath("checkpoint");
    fs.mkdirSync(output, { recursive: true });
    await page.setContent(detail(false, delivery === "manager" ? "admin" : "sales"));
    await expect(page.getByRole("button", { name: "重新读取", exact: true })).toHaveCount(0);
    const report = await recordAutomaticEntry(page, output, { delivery });
    expect(report).toMatchObject({ status: "passed", delivery, UI_idle_before_native_close: true });
    expect(JSON.parse(fs.readFileSync(output + "/native-autostart.json", "utf8"))).toEqual(report);
    expect(fs.existsSync(output + `/native-autostart-${delivery}.png`)).toBeTruthy();
  });
}

test("busy or disabled submitted workspace cannot publish a passing checkpoint", async ({ page }, testInfo) => {
  const output = testInfo.outputPath("checkpoint");
  fs.mkdirSync(output, { recursive: true });
  for (const busy of [true, false]) {
    await page.setContent(detail(busy));
    if (!busy) await page.getByRole("button", { name: "返回订单记录", exact: true }).evaluate(button => {
      (button as HTMLButtonElement).disabled = true;
    });
    let rejected = false;
    try { await recordAutomaticEntry(page, output, { delivery: "manager" }, 200); }
    catch { rejected = true; }
    expect(rejected).toBeTruthy();
    expect(fs.existsSync(output + "/native-autostart.json")).toBeFalsy();
    expect(fs.existsSync(output + "/native-autostart-manager.png")).toBeFalsy();
  }
});
