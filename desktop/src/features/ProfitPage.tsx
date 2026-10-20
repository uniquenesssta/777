import { useEffect, useState } from "react";
import type { AnalysisFilters, AnalysisPeriod } from "../contracts";
import type { Workbench } from "../state/useWorkbench";
import { money } from "../state/format";
import {
  chartTypes,
  type ProfitChart,
  profitRange,
  normalizeAnalysisTime,
  series,
  type ProfitPreset,
} from "../state/profit";
import { ProfitChartView } from "./ProfitCharts";
import { Button, Empty, Field, Input } from "../ui/components";
const periods: { value: AnalysisPeriod; label: string }[] = [
  { value: "day", label: "按日" },
  { value: "week", label: "按周" },
  { value: "month", label: "按月" },
  { value: "year", label: "按年" },
];
const presets: { value: ProfitPreset; label: string }[] = [
  { value: "day", label: "近1天" },
  { value: "week", label: "近1周" },
  { value: "month", label: "近1月" },
  { value: "year", label: "近1年" },
];
export function ProfitPage({ app }: { app: Workbench }) {
  const [filters, setFilters] = useState<AnalysisFilters>(app.analysisFilters);
  const [preset, setPreset] = useState(app.analysisPreset);
  useEffect(() => {
    setFilters(app.analysisFilters);
    setPreset(app.analysisPreset);
  }, [app.analysisFilters, app.analysisPreset]);
  const data = app.analysis;
  const [chart, setChart] = useState<ProfitChart>("bar");
  return (
    <section className="card profit-page">
      <div className="section-heading">
        <div>
          <h2>利润分析</h2>
          <p className="muted">
            {data
              ? `${data.from.replace("T", " ").slice(0, 16)} 至 ${data.to.replace("T", " ").slice(0, 16)} · 有效订单 ${data.totals.order_count} 笔`
              : "收入、成本与利润趋势"}
          </p>
        </div>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.loadAnalysis()}
        >
          刷新
        </Button>
      </div>
      <form
        className="analysis-filters"
        onSubmit={(e) => {
          e.preventDefault();
          void app.loadAnalysis(filters, preset);
        }}
      >
        <div className="period-buttons" role="group" aria-label="快捷时间">
          {presets.map((p) => (
            <Button
              key={p.value}
              variant={preset === p.value ? "primary" : "ghost"}
              aria-pressed={preset === p.value}
              disabled={app.busy}
              onClick={() => {
                const next = profitRange(p.value);
                setFilters(next);
                setPreset(p.value);
                void app.loadAnalysis(next, p.value);
              }}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <Field label="图表分组">
          <select
            aria-label="图表分组"
            value={filters.period}
            disabled={app.busy}
            onChange={(e) => {
              const next = {
                ...filters,
                period: e.target.value as AnalysisPeriod,
              };
              setFilters(next);
              void app.loadAnalysis(next, preset);
            }}
          >
            {periods.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="开始时间">
          <Input
            type="datetime-local"
            step="1"
            required
            disabled={app.busy}
            value={filters.from.slice(0, 19)}
            max={filters.to.slice(0, 19)}
            onChange={(e) => {
              setPreset(null);
              setFilters({
                ...filters,
                from: normalizeAnalysisTime(e.target.value),
              });
            }}
          />
        </Field>
        <Field label="结束时间">
          <Input
            type="datetime-local"
            step="1"
            required
            disabled={app.busy}
            value={filters.to.slice(0, 19)}
            min={filters.from.slice(0, 19)}
            onChange={(e) => {
              setPreset(null);
              setFilters({
                ...filters,
                to: normalizeAnalysisTime(e.target.value),
              });
            }}
          />
        </Field>
        <Button type="submit" disabled={app.busy}>
          查看汇总
        </Button>
      </form>
      <div className="analysis-metrics">
        {[
          { label: "总收入", value: money(data?.totals.income_cents) },
          { label: "总成本", value: money(data?.totals.cost_cents) },
          { label: "总利润", value: money(data?.totals.profit_cents) },
          { label: "综合利润率", value: data?.totals.margin ?? "—" },
        ].map((m, i) => (
          <article key={m.label} data-highlight={i === 2}>
            <small>{m.label}</small>
            <strong className="numeric">{m.value}</strong>
          </article>
        ))}
      </div>
      <div className="section-heading chart-heading">
        <h3>
          {chart === "pie"
            ? "各期间盈亏占比"
            : chart === "candle"
              ? "累计利润走势"
              : "收入与利润趋势"}
        </h3>
        <div className="period-buttons" role="group" aria-label="图表类型">
          {chartTypes.map((c) => (
            <Button
              key={c.value}
              variant={chart === c.value ? "primary" : "ghost"}
              aria-pressed={chart === c.value}
              onClick={() => setChart(c.value)}
            >
              {c.label}
            </Button>
          ))}
        </div>
      </div>
      {!data ? (
        <Empty>{app.working ? "正在读取汇总…" : !app.session ? "" : "请选择统计期间。"}</Empty>
      ) : !data.totals.order_count ? (
        <Empty>此期间没有有效订单。</Empty>
      ) : (
        <>
          <ProfitChartView data={data} chart={chart} />
          <details className="analysis-data">
            <summary>查看汇总数据</summary>
            <div className="orders-table-scroll">
              <table className="orders-table">
                <thead>
                  <tr>
                    <th>期间起始</th>
                    <th>订单数</th>
                    <th>收入（元）</th>
                    <th>成本（元）</th>
                    <th>利润（元）</th>
                    <th>利润率</th>
                  </tr>
                </thead>
                <tbody>
                  {data.buckets.map((b) => (
                    <tr key={b.start}>
                      <td>{b.start}</td>
                      <td>{b.totals.order_count}</td>
                      {series.map((s) => (
                        <td className="numeric" key={s.key}>
                          {money(b.totals[s.key])}
                        </td>
                      ))}
                      <td>{b.totals.margin ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      <p className="muted analysis-caption">
        按北京时间统计所选时段；图表按所选日、周、月、年分组，周一为每周起点，作废订单不计入。
      </p>
      {!!data?.unplaced_date_orders && (
        <p className="muted">
          {data.unplaced_date_orders} 笔历史订单日期无法识别，未归入时间汇总。
        </p>
      )}
    </section>
  );
}
