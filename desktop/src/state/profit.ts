import type {
  AnalysisPeriod,
  AnalysisFilters,
  ProfitAnalysis,
} from "../contracts";
export function profitRange(
  period: AnalysisPeriod,
  today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10),
): AnalysisFilters {
  const start = new Date(today + "T00:00:00Z");
  if (period === "day") start.setUTCDate(start.getUTCDate() - 29);
  if (period === "week")
    start.setUTCDate(
      start.getUTCDate() - ((start.getUTCDay() + 6) % 7) - 11 * 7,
    );
  if (period === "month") {
    start.setUTCDate(1);
    start.setUTCMonth(start.getUTCMonth() - 11);
  }
  if (period === "year") {
    start.setUTCFullYear(start.getUTCFullYear() - 4, 0, 1);
  }
  return { period, from: start.toISOString().slice(0, 10), to: today };
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
