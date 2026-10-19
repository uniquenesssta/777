// Actual DetailPage markup and browser locators; this is not native IPC acceptance.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { detailMarkup as detail } from "./fixtures/detail-page";
import { recordAutomaticEntry } from "../windows-autostart.mjs";

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
