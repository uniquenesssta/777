# 文档与计划入口

日期：2026-10-11（Asia/Shanghai）。仓库：`uniquenesssta/777`。规划基线分支：`plans`；当前执行分支：`stage/p03-file-safety`；P01收尾提交：`7099303`。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 审计基线 | `master@32e164d78643de8fa6cbd21a7ca634e1b318f855` |
| 本轮授权 | P03-01接续与既有推送授权有效；用户取消主动断网，要求真实共享双机/占用测试步骤，见[范围确认](verification/P03-01-scope.json) |
| 文档工作 | [P02归档任务书](old/P02-calculation.md)、[03 Windows证据](verification/P02-03-windows-evidence.json)、[03验收](verification/P02-03-acceptance.json)及[04辅助证据](verification/P02-04-checks.json)已登记；旧01/02/P01报告保留 |
| 当前开发阶段 / Atomic Task | P03-01 Windows本机32项与母子GUI联测通过，待真实共享盘/用户验收；[当前任务书](now/P03-file-safety.md)、[文件协议](verification/P03-01-file-protocol.md)、[辅助证据](verification/P03-01-checks.json)、[Windows回传](verification/P03-01-windows-evidence.json)。P01/P02已归档；P03-02至04和P04至P08未启动 |
| 下一项 | 按[双机步骤](verification/P03-01-shared-test.md)运行隔离共享测试；P03-01真实共享协议验证及用户验收；Windows本机32项与GUI已通过，无需重跑；P03-02须在01收尾后继续 |
| 业务源码 | 根目录原文件名现共用quote_app/quote_core；[原版归档](baseline/original/README.md)仍按原manifest校验，历史证据不改 |
| Windows / 局域网验收 | Windows隔离GUI和P01-04小档心跳已测；[格式复查18/18通过](baseline/p01-04-windows-format-evidence.json)，原性能缺陷保留；P02-01核心本机检查已通过（58通过、2跳过），P02-02本机检查已通过（76通过、2项既有权限跳过），新增18项配置全过；P02-03本机94通过/2项既有权限跳过，03已验收；完整业务、部署及SMB验收留后续 |

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
- 启动一个开发阶段时，先公告该阶段唯一分支名称和真实基线，再在授权内创建或复用；阶段内 Atomic Task 复用它。P01已在stage/p01-baseline收尾；P02在stage/p02-calculation收尾；P03复用唯一stage/p03-file-safety。
- P01实际分支 `stage/p01-baseline` 以已核验的 `plans@78a1e1d` 为基线，业务源码与master原始blob一致；P02实际分支stage/p02-calculation基于P01验收提交7099303；P03实际分支stage/p03-file-safety基于P02验收提交96735ad；P04至P08仍为拟议，后续基于前阶段已验收代码，不盲目从 master 重开。
- 开发分支携带当前任务书记录。需同步 plans 索引时只同步文档且核对最新状态；不要把 plans 旧代码合并回开发分支，不为了同步文档制造第二条开发分支。
- 恢复工作必须核对主任务书、now、真实分支/提交和工作区；三者不一致先查证，禁止从文件名推断完成。

## 规则依据

项目采用 [通用规则入口 AGENTS.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AGENTS.md)，并配套 [ALL_AI_CODE.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/ALL_AI_CODE.md)、[AI_PROJECT_RULES.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AI_PROJECT_RULES.md)。本次读取的规则仓库提交为 `c0a57ae1b391ba48bc0b20ae9f9c71eb0926ec40`。项目专属要求与当前用户授权同时适用，不在此复制一套分叉规则。

基线只有 LICENSE 和两份脚本，无 README、docs、依赖锁、测试或 CI 配置；本轮建立所需文档，未假设其他项目的阶段编号、Figma 或验证结果适用于本仓库。

当前结论（2026-10-11）：P01/P02已归档，P03-01复用stage/p03-file-safety，Windows本机32项及母子GUI联测通过；用户已正确切换跟踪分支。最新取消主动断网演练，提供真实共享双机/占用隔离入口及操作说明，仍待实机/用户验收。P03-02至04及P04至P08未启动，原始报告保留。
