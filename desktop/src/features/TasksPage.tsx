import { useEffect, useState } from "react";
import type { Workbench } from "../state/useWorkbench";
import { stamp } from "../state/format";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
} from "../ui/components";
export function TasksPage({ app }: { app: Workbench }) {
  const today=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const [from,setFrom]=useState(today.slice(0,7)+"-01"),[to,setTo]=useState(today);
  useEffect(() => {
    if (
      !app.jobs.some((j) =>
        ["queued", "running", "processing", "publishing"].includes(j.state),
      )
    )
      return;
    const timer = setInterval(() => {
      if (!app.busy) void app.loadJobs();
    }, 1500);
    return () => clearInterval(timer);
  }, [app.jobs, app.busy, app.loadJobs]);
  return (
    <section className="card management">
      <div className="section-heading">
        <h2>
          导出记录 <small>{app.jobsMore === true ? `已读取 ${app.jobsOffset+app.jobs.length} 项` : `共 ${app.jobsTotal} 项`}</small>
        </h2>
        <Button
          variant="ghost"
          disabled={app.busy}
          onClick={() => void app.loadJobs()}
        >
          刷新
        </Button>
      </div>
      <p className="muted export-purpose">
        在订单详情点击“导出报价”“报价图片”
        {app.can("finance") ? "或“内部财务报表”" : ""}
        后，可在这里查看进度和保存结果，失败时重试。
      </p>
      {app.can("finance")&&<form className="order-filters" onSubmit={e=>{e.preventDefault();void app.createReport(from,to);}}><strong>内部财务报表</strong><Field label="报表开始日期"><Input type="date" required value={from} max={to} onChange={e=>setFrom(e.target.value)}/></Field><Field label="报表结束日期"><Input type="date" required value={to} min={from} onChange={e=>setTo(e.target.value)}/></Field><Button type="submit" disabled={app.busy||app.pending||!from||!to||from>to}>导出 Excel</Button><small>按月分表、月内按日；大范围自动分文件，单月过大时按完整订单分批。</small></form>}
      <div className="orders-table-scroll">
        <table className="orders-table">
          <thead>
            <tr>
              <th>导出内容</th>
              <th>订单</th>
              <th>创建时间</th>
              <th>状态</th>
              <th>结果</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {app.jobs.map((j) => (
              <tr key={j.job_id}>
                <td>
                  {{
                    excel_quote: "报价表",
                    excel_admin: "内部财务报表",
                    excel_period: "内部财务报表（期间）",
                    quote_png: "报价图片",
                  }[j.kind] ?? j.kind}
                  {j.batch&&j.batch.count>1&&<small className="report-part" title={`导出批次 ${j.batch.id}`}>第 {j.batch.part} / {j.batch.count} 份 · {j.batch.order_count} 笔订单<br/>{j.batch.from} 至 {j.batch.to}</small>}
                </td>
                <td>
                  {j.kind==="excel_period"?<span>{j.range?.from} 至 {j.range?.to}</span>:<Button
                    variant="ghost"
                    onClick={() => void app.readOrder(j.order_id)}
                    disabled={app.busy}
                  >
                    {j.order_id.slice(0, 8)}
                  </Button>}
                </td>
                <td>{stamp(j.created_at)}</td>
                <td>
                  <Badge muted={j.state === "failed"}>
                    {{
                      queued: "等待处理",
                      running: "正在处理",
                      publishing: "正在保存",
                      done: "已完成",
                      failed: "失败",
                    }[j.state] ?? j.state}
                  </Badge>
                </td>
                <td>
                  {j.state === "done" ? "文件已生成" : (!app.formal && j.error) || "—"}
                </td>
                <td>
                  {j.state === "done" && (
                    <Button variant="ghost" disabled={app.busy} title="打开该次导出文件所在的文件夹" onClick={() => void app.openOutputFolder(j.job_id)}>打开文件夹</Button>
                  )}
                  {j.state === "failed" && (
                    <Button
                      variant="outline"
                      disabled={app.busy || app.pending}
                      onClick={() => void app.retryOutput(j.job_id)}
                    >
                      重新导出
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pagination">
          <Button variant="ghost" disabled={app.busy||app.jobsOffset===0} onClick={()=>void app.loadJobs(Math.max(0,app.jobsOffset-100))}>上一页</Button>
          <small>第 {Math.floor(app.jobsOffset/100)+1}{app.jobsMore === undefined ? ` / ${Math.max(1,Math.ceil(app.jobsTotal/100))}` : ""} 页</small>
          <Button variant="ghost" disabled={app.busy||app.jobsOffset+100>=app.jobsTotal} onClick={()=>void app.loadJobs(app.jobsOffset+100)}>下一页</Button>
        </div>
        {!app.jobs.length && (
          <Empty>暂无导出记录，可在订单详情导出Excel或报价图片。</Empty>
        )}
      </div>
    </section>
  );
}
