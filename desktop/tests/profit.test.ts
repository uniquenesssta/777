import test from "node:test";
import assert from "node:assert/strict";
import {
  businessNow,
  normalizeAnalysisTime,
  chartDomain,
  chartFraction,
  profitRange,
} from "../src/state/profit.ts";
import type { ProfitAnalysis } from "../src/contracts.ts";

test("shortcuts span exactly one day, week, month or year from the same current instant", () => {
  const now = "2026-10-15T14:41:10.123";
  for (const [preset, from, period] of [
    ["day", "2026-10-14T14:41:10.123", "day"],
    ["week", "2026-10-08T14:41:10.123", "day"],
    ["month", "2026-09-15T14:41:10.123", "day"],
    ["year", "2025-10-15T14:41:10.123", "month"],
  ] as const)
    assert.deepEqual(profitRange(preset, now), { period, from, to: now });
});

test("calendar subtraction clamps month ends and leap anniversaries while keeping the clock", () => {
  assert.equal(
    profitRange("month", "2026-03-31T14:41:10.123").from,
    "2026-02-28T14:41:10.123",
  );
  assert.equal(
    profitRange("month", "2024-03-31T14:41:10.123").from,
    "2024-02-29T14:41:10.123",
  );
  assert.equal(
    profitRange("year", "2024-02-29T14:41:10.123").from,
    "2023-02-28T14:41:10.123",
  );
  assert.equal(
    profitRange("month", "2026-01-04T14:41:10.123").from,
    "2025-12-04T14:41:10.123",
  );
});

test("business clock uses UTC+08 across midnight rather than the device timezone", () => {
  assert.equal(
    businessNow(Date.parse("2026-12-31T15:59:59.999Z")),
    "2026-12-31T23:59:59.999",
  );
  assert.equal(
    businessNow(Date.parse("2026-12-31T16:00:00.000Z")),
    "2027-01-01T00:00:00.000",
  );
});

test("datetime picker minute and abbreviated subsecond values keep a canonical exact boundary", () => {
  for (const [raw, expected] of [
    ["2026-10-15T14:41", "2026-10-15T14:41:00.000"],
    ["2026-10-15T14:41:10", "2026-10-15T14:41:10.000"],
    ["2026-10-15T14:41:10.12", "2026-10-15T14:41:10.120"],
    ["2026-10-15T14:41:10.123", "2026-10-15T14:41:10.123"],
    ["", ""],
  ])
    assert.equal(normalizeAnalysisTime(raw), expected);
});

test("chart coordinates support losses and huge exact cents without converting money to Number", () => {
  const huge = "900719925474099300000";
  const data = {
    buckets: [
      {
        totals: {
          income_cents: huge,
          cost_cents: "1",
          profit_cents: "-900719925474099300000",
        },
      },
    ],
  } as ProfitAnalysis;
  const domain = chartDomain(data);
  assert.equal(domain.max, BigInt(huge));
  assert.equal(domain.min, -BigInt(huge));
  assert.equal(chartFraction(domain.max, domain.min, domain.max), 0);
  assert.equal(chartFraction(0n, domain.min, domain.max), 0.5);
  assert.equal(chartFraction(domain.min, domain.min, domain.max), 1);
  assert.deepEqual(chartDomain({ buckets: [] } as unknown as ProfitAnalysis), {
    min: 0n,
    max: 100n,
  });
});

test("profit pie keeps losses explicit and computes exact shares for huge cents and zero buckets", async () => {
  const { profitSlices } = await import("../src/state/profit.ts");
  const data = {
    buckets: [
      {
        start: "2026-01-01",
        totals: { profit_cents: "-900719925474099300000" },
      },
      {
        start: "2026-01-02",
        totals: { profit_cents: "2702159776422297900000" },
      },
      { start: "2026-01-03", totals: { profit_cents: "0" } },
    ],
  } as ProfitAnalysis;
  const result = profitSlices(data);
  assert.equal(result.total, 3602879701896397200000n);
  assert.equal(result.slices.length, 2);
  assert.deepEqual(
    result.slices.map((s) => [s.from, s.to, s.percent]),
    [
      [0, 0.25, "25.0%"],
      [0.25, 1, "75.0%"],
    ],
  );
  assert.equal(result.slices[0].profit, -900719925474099300000n);
  assert.deepEqual(
    profitSlices({
      buckets: [{ totals: { profit_cents: "0" } }],
    } as ProfitAnalysis),
    { total: 0n, slices: [] },
  );
  assert.equal(
    profitSlices({ buckets: [data.buckets[0]] } as ProfitAnalysis).slices[0]
      .percent,
    "100.0%",
  );
});

test("candle domain includes intra-period high and low rather than only closing totals", async () => {
  const { candleDomain } = await import("../src/state/profit.ts");
  const data = {
    buckets: [
      {
        profit_ohlc: {
          open_cents: "0",
          high_cents: "900719925474099300000",
          low_cents: "-700000000000000000000",
          close_cents: "1",
        },
      },
    ],
  } as ProfitAnalysis;
  assert.deepEqual(candleDomain(data), {
    min: -700000000000000000000n,
    max: 900719925474099300000n,
  });
  assert.deepEqual(candleDomain({ buckets: [] } as unknown as ProfitAnalysis), {
    min: 0n,
    max: 100n,
  });
});
