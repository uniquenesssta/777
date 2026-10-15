import { useEffect, useRef, useState } from "react";
import type { ProfitAnalysis } from "../contracts";
import { money } from "../state/format";
import {
  candleDomain,
  chartDomain,
  chartFraction,
  profitSlices,
  series,
  type ProfitChart,
} from "../state/profit";
import { Empty } from "../ui/components";

const rise = "#5558e8",
  fall = "#14846c";
const candleFields = [
  { key: "open_cents", label: "开" },
  { key: "high_cents", label: "高" },
  { key: "low_cents", label: "低" },
  { key: "close_cents", label: "收" },
] as const;
const label = (data: ProfitAnalysis, start: string) =>
  data.period === "year" ? start.slice(0, 4) : start.slice(5);

export function ProfitChartView({
  data,
  chart,
}: {
  data: ProfitAnalysis;
  chart: ProfitChart;
}) {
  return chart === "pie" ? (
    <ProfitPie data={data} />
  ) : (
    <TrendChart data={data} chart={chart} />
  );
}
function TrendChart({
  data,
  chart,
}: {
  data: ProfitAnalysis;
  chart: Exclude<ProfitChart, "pie">;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(760);
  useEffect(() => {
    if (!scroll.current) return;
    const observer = new ResizeObserver(() =>
      setAvailable(scroll.current?.clientWidth ?? 760),
    );
    observer.observe(scroll.current);
    return () => observer.disconnect();
  }, [chart, data]);
  const candle = chart === "candle";
  if (candle && data.buckets.some((b) => !b.profit_ohlc))
    return <Empty>当前服务未提供K线数据，请更新服务后刷新。</Empty>;
  const domain = candle ? candleDomain(data) : chartDomain(data);
  const top = 20,
    height = 230,
    left = 150;
  const width = Math.max(360, available, data.buckets.length * 56 + left + 24);
  const y = (n: bigint) =>
    top + chartFraction(n, domain.min, domain.max) * height;
  const x = (i: number) =>
    left + ((i + 0.5) * (width - left - 24)) / data.buckets.length;
  const baseline = y(0n);
  const title = candle
    ? "累计利润K线图"
    : chart === "line"
      ? "收入成本利润折线图"
      : "收入成本利润柱状图";
  return (
    <div className="profit-chart">
      <div className="chart-legend">
        {candle ? (
          <>
            <span>
              <i style={{ background: rise }} />
              上涨 / 持平
            </span>
            <span>
              <i style={{ background: fall }} />
              下跌
            </span>
          </>
        ) : (
          series.map((s) => (
            <span key={s.key}>
              <i style={{ background: s.color }} />
              {s.label}
            </span>
          ))
        )}
      </div>
      <div
        className="profit-chart-scroll"
        ref={scroll}
        tabIndex={0}
        role="region"
        aria-label={title}
      >
        <svg
          width={width}
          height={310}
          viewBox={`0 0 ${width} 310`}
          role="img"
          aria-label={`${data.from}至${data.to}${title}`}
        >
          {[0, 1, 2, 3, 4].map((t) => {
            const amount =
              domain.max - ((domain.max - domain.min) * BigInt(t)) / 4n;
            const at = top + (height * t) / 4;
            return (
              <g key={t}>
                <line
                  x1={left}
                  x2={width - 16}
                  y1={at}
                  y2={at}
                  stroke="#e7e9ef"
                />
                <text
                  x={left - 12}
                  y={at + 4}
                  textAnchor="end"
                  className="chart-axis numeric"
                >
                  {money(amount.toString())}
                </text>
              </g>
            );
          })}
          <line
            x1={left}
            x2={width - 16}
            y1={baseline}
            y2={baseline}
            stroke="#a3a7b2"
          />
          {chart === "line" &&
            series.map((s) => (
              <polyline
                key={s.key}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                points={data.buckets
                  .map((b, i) => `${x(i)},${y(BigInt(b.totals[s.key]))}`)
                  .join(" ")}
              />
            ))}
          {data.buckets.map((b, i) => {
            const text =
              candle && b.profit_ohlc
                ? candleFields
                    .map((f) => `${f.label}${money(b.profit_ohlc![f.key])}`)
                    .join("，")
                : series
                    .map((s) => `${s.label}${money(b.totals[s.key])}`)
                    .join("，");
            return (
              <g
                key={b.start}
                tabIndex={0}
                role="img"
                aria-label={`${b.start}，${b.totals.order_count}笔，${text}`}
              >
                <title>{`${b.start} · ${b.totals.order_count} 笔\n${text}元`}</title>
                {candle && b.profit_ohlc
                  ? (() => {
                      const v = b.profit_ohlc;
                      const open = y(BigInt(v.open_cents)),
                        close = y(BigInt(v.close_cents));
                      const color =
                        BigInt(v.close_cents) >= BigInt(v.open_cents)
                          ? rise
                          : fall;
                      return (
                        <>
                          <line
                            x1={x(i)}
                            x2={x(i)}
                            y1={y(BigInt(v.high_cents))}
                            y2={y(BigInt(v.low_cents))}
                            stroke={color}
                            strokeWidth={2}
                          />
                          {v.open_cents === v.close_cents ? (
                            <line
                              x1={x(i) - 10}
                              x2={x(i) + 10}
                              y1={open}
                              y2={open}
                              stroke={color}
                              strokeWidth={2}
                              strokeDasharray={
                                b.totals.order_count ? undefined : "3 2"
                              }
                            />
                          ) : (
                            <rect
                              x={x(i) - 10}
                              y={Math.min(open, close)}
                              width={20}
                              height={Math.max(1, Math.abs(open - close))}
                              fill={color}
                              rx={1}
                            />
                          )}
                        </>
                      );
                    })()
                  : series.map((s, j) => {
                      const at = y(BigInt(b.totals[s.key]));
                      return chart === "line" ? (
                        <circle
                          key={s.key}
                          cx={x(i)}
                          cy={at}
                          r={3.5}
                          fill={s.color}
                        />
                      ) : (
                        <rect
                          key={s.key}
                          x={x(i) + (j - 1) * 11 - 4}
                          y={Math.min(at, baseline)}
                          width={8}
                          height={Math.abs(at - baseline)}
                          rx={2}
                          fill={s.color}
                        />
                      );
                    })}
                <text
                  x={x(i)}
                  y={height + top + 24}
                  textAnchor="middle"
                  className="chart-axis"
                >
                  {label(data, b.start)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {candle && (
        <p className="muted analysis-caption">
          所选时段累计利润从0开始；每根K线为该分组内的开、高、低、收，同一时刻订单合并计算，无订单时延续上一收值。
        </p>
      )}
      {candle && (
        <details className="analysis-data">
          <summary>查看K线数据</summary>
          <div className="orders-table-scroll">
            <table className="orders-table">
              <thead>
                <tr>
                  <th>期间起始</th>
                  <th>订单数</th>
                  {candleFields.map((f) => (
                    <th key={f.key}>{f.label}（元）</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.buckets.map((b) => (
                  <tr key={b.start}>
                    <td>{b.start}</td>
                    <td>{b.totals.order_count}</td>
                    {candleFields.map((f) => (
                      <td className="numeric" key={f.key}>
                        {money(b.profit_ohlc![f.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
function ProfitPie({ data }: { data: ProfitAnalysis }) {
  const { total, slices } = profitSlices(data);
  if (!total) return <Empty>各期间净利润均为0，暂无占比。</Empty>;
  const color = (i: number, negative: boolean) =>
    `hsl(${negative ? 8 : 245} 65% ${42 + (i % 6) * 6}%)`;
  const point = (fraction: number) => {
    const angle = fraction * Math.PI * 2 - Math.PI / 2;
    return `${130 + 108 * Math.cos(angle)} ${130 + 108 * Math.sin(angle)}`;
  };
  return (
    <div className="profit-pie" role="region" aria-label="各期间盈亏占比饼图">
      <svg
        width={260}
        height={260}
        viewBox="0 0 260 260"
        role="img"
        aria-label="各期间净利润绝对值占比，亏损单独标注"
      >
        {slices.map((s, i) => {
          const text = `${s.start} ${s.profit < 0n ? "亏损" : "盈利"}${money(s.profit.toString())}元，占比${s.percent}`;
          return (
            <g key={s.start} role="img" aria-label={text} tabIndex={0}>
              <title>{text}</title>
              {slices.length === 1 ? (
                <circle
                  cx={130}
                  cy={130}
                  r={108}
                  fill={color(i, s.profit < 0n)}
                />
              ) : (
                <path
                  d={`M 130 130 L ${point(s.from)} A 108 108 0 ${s.to - s.from > 0.5 ? 1 : 0} 1 ${point(s.to)} Z`}
                  fill={color(i, s.profit < 0n)}
                  stroke="white"
                  strokeWidth={1}
                />
              )}
            </g>
          );
        })}
      </svg>
      <div className="pie-details">
        <p className="muted analysis-caption">
          各期间净利润取绝对值计算占比；亏损使用暖色并标出负金额。盈亏绝对值合计
          ¥{money(total.toString())}。
        </p>
        <ul className="pie-legend">
          {slices.map((s, i) => (
            <li key={s.start}>
              <i style={{ background: color(i, s.profit < 0n) }} />
              <span>
                {s.start} · {s.profit < 0n ? "亏损" : "盈利"}
              </span>
              <b className="numeric">{money(s.profit.toString())}</b>
              <span>{s.percent}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
