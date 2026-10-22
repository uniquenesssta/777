import type { Calculation, Money } from "../contracts";
import { money } from "./format";
const MAX = 9223372036854775807n;
export function finalPriceCents(raw: string): bigint | null | undefined {
  const value = raw.trim();
  if (!value) return null;
  if (value.length > 32 || !/^\d+(?:\.\d{0,2})?$/.test(value)) return undefined;
  const [whole, fraction = ""] = value.split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return cents <= MAX ? cents : undefined;
}
export function settlement(result: Calculation | null, raw: string) {
  const manual = finalPriceCents(raw);
  const calculated = result?.status === "ok" && result.totals
    ? result.lines.reduce((sum, line) => sum + BigInt(line.income_cents), 0n) : null;
  let valid = manual !== undefined;
  let totals: Money | null = null;
  if (calculated !== null && valid && result?.totals) {
    const income = manual ?? calculated;
    totals = {income_cents: income.toString()};
    if (result.totals.cost_cents !== undefined) {
      const cost = BigInt(result.totals.cost_cents), profit = income - cost;
      valid = profit >= -MAX && profit <= MAX;
      const numerator = (profit < 0n ? -profit : profit) * 1000n;
      const rate = income === 0n ? 0n : (numerator * 2n + income) / (income * 2n);
      totals = {...totals, cost_cents: cost.toString(), profit_cents: profit.toString(), financial_display: {
        income: money(income.toString(), false), cost: money(cost.toString(), false), profit: money(profit.toString(), false),
        margin: income === 0n ? null : `${profit < 0n && rate !== 0n ? "-" : ""}${rate / 10n}.${rate % 10n}%`,
      }};
    }
  }
  return {valid, calculated: calculated?.toString(), totals: valid ? totals : null};
}
