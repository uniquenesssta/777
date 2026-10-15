import test from "node:test";
import assert from "node:assert/strict";
import {
  chartDomain,
  chartFraction,
  profitRange,
} from "../src/state/profit.ts";
import type { ProfitAnalysis } from "../src/contracts.ts";

test("calendar ranges cross years and leap days without local timezone arithmetic", () => {
  assert.deepEqual(profitRange("day", "2024-03-01"), {
    period: "day",
    from: "2024-02-01",
    to: "2024-03-01",
  });
  assert.deepEqual(profitRange("week", "2026-01-04"), {
    period: "week",
    from: "2025-10-13",
    to: "2026-01-04",
  });
  assert.deepEqual(profitRange("month", "2026-01-04"), {
    period: "month",
    from: "2025-02-01",
    to: "2026-01-04",
  });
  assert.deepEqual(profitRange("year", "2026-01-04"), {
    period: "year",
    from: "2022-01-01",
    to: "2026-01-04",
  });
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
