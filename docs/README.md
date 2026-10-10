# 文档与计划入口

日期：2026-10-10（Asia/Shanghai）。仓库：`uniquenesssta/777`。规划基线分支：`plans`；当前执行分支：`stage/p01-baseline`。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 审计基线 | `master@32e164d78643de8fa6cbd21a7ca634e1b318f855` |
| 本轮授权 | 已开始P01-04；既有仓库推送授权有效；P02及后续任务尚未启动 |
| 文档工作 | [P01-04黄金/格式/技术参数/验收材料](baseline/P01-04-validation.md)已交付；原业务源码未改 |
| 当前开发阶段 / Atomic Task | P01阶段未完成；P01-01至03已验收，04材料已交付，Windows原测已登记，待格式兼容修复的Windows复查与阶段材料验收，business-v1保持冻结 |
| 下一项 | 只运行P01-04格式复查入口、回传summary.json；已测黄金/规模/GUI不重跑，采纳/调整技术建议并完成P01验收；[目录/备份需求](baseline/P01-03-directory-backup.md)按P03/P05/P07/P08实施，未知真实旧格式/主机版本等保留到实际导入/部署前核实 |
| 业务源码 | 两份原始脚本保留原路径、原内容 |
| Windows / 局域网验收 | Windows隔离GUI和P01-04小档心跳已测；格式缓存样本修复待复查；完整业务、部署及SMB验收留后续 |

[主任务书](MASTER_PLAN.md) 是计划、阶段状态和阶段入口的权威索引；[审计报告](audit/python-audit.md) 保存证据；[迁移契约](MIGRATION_CONTRACT.md) 保存业务、字段与数据规则；[架构方案](RUST_TAURI_DESIGN.md) 保存拟议边界。根 README 的 Change Log 是唯一变更摘要，不再创建平行日志。

## new / now / old 生命周期

| 目录 | 内容 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| [new](new/README.md) | 待确认、已规划但未授权启动的阶段任务书 | 计划已形成，可包含明确待决项 | 收到启动授权，核对前置验收、分支和基线后，用 git mv 移入 now |
| [now](now/README.md) | 当前执行阶段唯一权威任务书 | 已授权且前置门槛满足 | 所有硬性验收通过后移入 old；受阻或未通过继续留在 now |
| [old](old/README.md) | 已验收完成、明确取消或被新计划替代的任务书 | 附验收证据，或注明取消/替代原因与接替计划 | 只修正事实或补充交叉链接，不直接从归档继续实施 |

阶段文件统一为 `Pxx-职责.md`；Atomic Task 为 `Pxx-01` 等，写在阶段文件内，不机械拆成几十个空文件。阶段执行状态使用：待启动、执行中、已实现待验证、验证受阻、待用户验收、已验收、已取消、已替代。被替代不等于验收通过。

一次移动同步更新主任务书和相关相对链接，不在 new/now 保留重复副本。Git 不跟踪空目录，各目录的 README 用于保留目录及说明。审计报告位于 `audit`，不冒充已验收的开发任务书。

## 分支策略与续接

- `plans` 仅承载规划及其记录；本轮从上述 master 基线创建。不得向 main/master 顺带提交。
- 启动一个开发阶段时，先公告该阶段唯一分支名称和真实基线，再在授权内创建或复用；阶段内 Atomic Task 复用它。当前已创建stage/p01-baseline；未创建其他开发阶段分支。
- P01实际分支 `stage/p01-baseline` 以已核验的 `plans@78a1e1d` 为基线，业务源码与master原始blob一致；P02至P08分支仍为拟议；后续基于前阶段已验收代码，不盲目从 master 重开。
- 开发分支携带当前任务书记录。需同步 plans 索引时只同步文档且核对最新状态；不要把 plans 旧代码合并回开发分支，不为了同步文档制造第二条开发分支。
- 恢复工作必须核对主任务书、now、真实分支/提交和工作区；三者不一致先查证，禁止从文件名推断完成。

## 规则依据

项目采用 [通用规则入口 AGENTS.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AGENTS.md)，并配套 [ALL_AI_CODE.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/ALL_AI_CODE.md)、[AI_PROJECT_RULES.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AI_PROJECT_RULES.md)。本次读取的规则仓库提交为 `c0a57ae1b391ba48bc0b20ae9f9c71eb0926ec40`。项目专属要求与当前用户授权同时适用，不在此复制一套分叉规则。

基线只有 LICENSE 和两份脚本，无 README、docs、依赖锁、测试或 CI 配置；本轮建立所需文档，未假设其他项目的阶段编号、Figma 或验证结果适用于本仓库。
