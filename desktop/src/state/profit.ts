import type {
  AnalysisPeriod,
  AnalysisFilters,
  ProfitAnalysis,
} from "../contracts";
export type ProfitPreset = AnalysisPeriod;
export function businessNow(now = Date.now()) {
  return new Date(now + 8 * 3600000).toISOString().slice(0, -1);
}
export function normalizeAnalysisTime(value: string) {
  const parts =
    /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(
      value,
    );
  return parts
    ? `${parts[1]}:${parts[2] ?? "00"}.${(parts[3] ?? "").padEnd(3, "0")}`
    : value;
}
export function profitRange(
  preset: ProfitPreset,
  now = businessNow(),
): AnalysisFilters {
  // UTC fields represent a fixed UTC+08 business wall clock, not the device zone.
  const end = new Date(now + "Z");
  const start = new Date(end.getTime());
  if (preset === "day" || preset === "week") {
    start.setUTCDate(start.getUTCDate() - (preset === "day" ? 1 : 7));
  } else {
    const day = start.getUTCDate();
    start.setUTCDate(1);
    start.setUTCMonth(start.getUTCMonth() - (preset === "month" ? 1 : 12));
    const last = new Date(
      Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0),
    ).getUTCDate();
    start.setUTCDate(Math.min(day, last));
  }
  return {
    period: preset === "year" ? "month" : "day",
    from: start.toISOString().slice(0, -1),
    to: end.toISOString().slice(0, -1),
  };
}
export const series = [
  { key: "income_cents", label: "收入", color: "#9892ee" },
  { key: "cost_cents", label: "成本", color: "#c6c9d5" },
  { key: "profit_cents", label: "利润", color: "#5558e8" },
] as const;
export function chartDomain(data: ProfitAnalysis) {
  let min = 0n,
    max = 0n;
  for (const b of data.buckets)
    for (const s of series) {
      const n = BigInt(b.totals[s.key]);
      if (n < min) min = n;
      if (n > max) max = n;
    }
  if (min === max) max = 100n;
  return { min, max };
}
// Only the bounded visual coordinate becomes Number; monetary values stay strings.
export function chartFraction(value: bigint, min: bigint, max: bigint) {
  return Number(((max - value) * 10000n) / (max - min)) / 10000;
}

export type ProfitChart = "bar" | "line" | "pie" | "candle";
export const chartTypes: { value: ProfitChart; label: string }[] = [
  { value: "bar", label: "柱状图" },
  { value: "line", label: "折线图" },
  { value: "pie", label: "饼图" },
  { value: "candle", label: "K线图" },
];
export function candleDomain(data: ProfitAnalysis) {
  let min = 0n,
    max = 0n;
  for (const b of data.buckets) {
    if (!b.profit_ohlc) continue;
    min =
      BigInt(b.profit_ohlc.low_cents) < min
        ? BigInt(b.profit_ohlc.low_cents)
        : min;
    max =
      BigInt(b.profit_ohlc.high_cents) > max
        ? BigInt(b.profit_ohlc.high_cents)
        : max;
  }
  if (min === max) max = min + 100n;
  return { min, max };
}
export function profitSlices(data: ProfitAnalysis) {
  const items = data.buckets.map((b) => ({
    start: b.start,
    profit: BigInt(b.totals.profit_cents),
  }));
  const total = items.reduce(
    (sum, item) => sum + (item.profit < 0n ? -item.profit : item.profit),
    0n,
  );
  let previous = 0n;
  return {
    total,
    slices: items
      .filter((item) => item.profit !== 0n)
      .map((item) => {
        const absolute = item.profit < 0n ? -item.profit : item.profit;
        const from = Number((previous * 1000000n) / total) / 1000000;
        previous += absolute;
        const to = Number((previous * 1000000n) / total) / 1000000;
        return {
          ...item,
          from,
          to,
          percent: `${(absolute * 1000n + total / 2n) / total / 10n}.${((absolute * 1000n + total / 2n) / total) % 10n}%`,
        };
      }),
  };
}
