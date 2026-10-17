import { test } from "node:test";
import assert from "node:assert/strict";
import { managedLocation } from "../src/features/settings/managedLocations.ts";

test("formal location labels conceal the selected service address without changing stored paths", () => {
  for (const delivery of ["manager", "sales"]) {
    for (const value of ["\\\\192.168.4.23\\共享\\backup", "https://192.168.4.23:8477", "\\\\192.168.4.23\\订单"])
      assert.deepEqual(managedLocation(value, delivery, "每日备份"), { concealed: true, display: "已配置的每日备份位置" });
  }
});

test("development and other destinations remain readable, including addresses sharing a numeric prefix", () => {
  for (const value of ["C:\\业务数据", "\\\\192.168.4.38\\报价", "\\\\192.168.4.230\\报价", ""]) {
    assert.deepEqual(managedLocation(value, "manager", "报价表"), { concealed: false, display: value });
  }
  const value = "\\\\192.168.4.23\\共享\\backup";
  assert.deepEqual(managedLocation(value, "development", "每日备份"), { concealed: false, display: value });
});
