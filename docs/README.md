# 文档与计划入口

日期：2026-10-13（Asia/Shanghai）。仓库：`uniquenesssta/777`。规划基线分支：`plans`；当前执行分支：`stage/p05-data-service`；P01收尾提交：`7099303`。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 审计基线 | `master@32e164d78643de8fa6cbd21a7ca634e1b318f855` |
| 本轮授权 | 用户2026-10-13 00:12:35确认停电、授权先推进P05并延期共享复验；既有推送授权有效 |
| 文档工作 | [P02归档任务书](old/P02-calculation.md)、[03 Windows证据](verification/P02-03-windows-evidence.json)、[03验收](verification/P02-03-acceptance.json)及[04辅助证据](verification/P02-04-checks.json)已登记；旧01/02/P01报告保留 |
| 当前开发阶段 / Atomic Task | P01/P02/P03已验收；P04已依据[接续指令](verification/P04-acceptance.json)验收收尾，原正式06本机/UNC全档通过证据保持。当前唯一stage/p05-data-service；P05-01已按用户“收尾01开始02”[验收收尾](verification/P05-01-acceptance.json)，原Windows42/42及恢复/权限通过证据不改。P05-02从84b881c实现[HTTPS认证服务与母子版适配](verification/P05-02-service-contract.md)，主体/会话/角色DTO、原请求核查、子版只读继承目录、主机备份计划和完整服务恢复已交付，[42专项/427完整辅助](verification/P05-02-checks.json)通过；[完整Windows核对](verification/P05-02-windows-report-verification-01.json)确认60项源码指纹、42测试ID一致，42/42零失败/错误/跳过及实际母子Tk/DPAPI/恢复/权限/清理通过，无需重跑；真实主机/E盘和物理双机部署仍待验证。P05-02隔离交付已[收尾](verification/P05-02-acceptance.json)；P05-03已实现[旧数据预演/原子导入](verification/P05-03-import-contract.md)，[50专项/477完整辅助](verification/P05-03-checks.json)通过，原Windows50/50及41项指纹核对已按[用户指令](verification/P05-03-acceptance.json)验收收尾，无需重跑。当前P05-04已实现[报表/附件任务与增量查询](verification/P05-04-output-contract.md)，[50专项/527完整辅助](verification/P05-04-checks.json)通过，38项验证入口指纹，待本轮Windows隔离验证。P05-04已交付待Windows/用户验收，P06未启动，未迁移或切换生产数据。 |
| 下一项 | P05-03已按用户“收尾03开始04”验收；运行[P05-04新Windows入口](verification/P05-04-output-contract.md)，无需重跑旧通过检查；P06未启动 |
| 业务源码 | 根目录原文件名现共用quote_app/quote_core；[原版归档](baseline/original/README.md)仍按原manifest校验，历史证据不改 |
| Windows / 局域网验收 | Windows隔离GUI和P01-04小档心跳已测；[格式复查18/18通过](baseline/p01-04-windows-format-evidence.json)，原性能缺陷保留；P02-01核心本机检查已通过（58通过、2跳过），P02-02本机检查已通过（76通过、2项既有权限跳过），新增18项配置全过；P02-03本机94通过/2项既有权限跳过，03已验收；完整业务、部署及SMB验收留后续 |

[主任务书](MASTER_PLAN.md) 是计划、阶段状态和阶段入口的权威索引；[审计报告](audit/python-audit.md) 保存证据；[迁移契约](MIGRATION_CONTRACT.md) 保存业务、字段与数据规则；[架构方案](RUST_TAURI_DESIGN.md) 保存拟议边界。根 README 的 Change Log 是唯一变更摘要，不再创建平行日志。

## new / now / old 生命周期

| 目录 | 内容 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| [new](new/README.md) | 待确认、已规划但未授权启动的阶段任务书 | 计划已形成，可包含明确待决项 | 收到启动授权，核对前置验收、分支和基线后，用 git mv 移入 now |
| [now](now/README.md) | 当前执行阶段唯一权威任务书 | 已授权且前置门槛满足 | 所有硬性验收通过后移入 old；受阻或未通过一般留now；用户明确授权后续计划接替时，可注明未验收事实转接old并在新任务书保留待办 |
| [old](old/README.md) | 已验收完成、明确取消或被新计划替代的任务书 | 附验收证据，或注明取消/替代原因与接替计划 | 只修正事实或补充交叉链接，不直接从归档继续实施 |

阶段文件统一为 `Pxx-职责.md`；Atomic Task 为 `Pxx-01` 等，写在阶段文件内，不机械拆成几十个空文件。阶段执行状态使用：待启动、执行中、已实现待验证、验证受阻、待用户验收、已验收、已取消、已替代。被替代不等于验收通过。

一次移动同步更新主任务书和相关相对链接，不在 new/now 保留重复副本。Git 不跟踪空目录，各目录的 README 用于保留目录及说明。审计报告位于 `audit`，不冒充已验收的开发任务书。

## 分支策略与续接

- `plans` 仅承载规划及其记录；本轮从上述 master 基线创建。不得向 main/master 顺带提交。
- 启动一个开发阶段时，先公告该阶段唯一分支名称和真实基线，再在授权内创建或复用；阶段内 Atomic Task 复用它。P01已在stage/p01-baseline收尾；P02在stage/p02-calculation收尾；P03在stage/p03-file-safety收尾；P04复用唯一stage/p04-performance。
- P01实际分支 `stage/p01-baseline` 以已核验的 `plans@78a1e1d` 为基线，业务源码与master原始blob一致；P02实际分支stage/p02-calculation基于P01验收提交7099303；P03实际分支stage/p03-file-safety基于P02验收提交96735ad；P04实际分支stage/p04-performance基于P03验收提交823a487；P05已按用户依赖例外授权从31c8784建立stage/p05-data-service；P06至P08仍为拟议，不盲目从master重开。
- 开发分支携带当前任务书记录。需同步 plans 索引时只同步文档且核对最新状态；不要把 plans 旧代码合并回开发分支，不为了同步文档制造第二条开发分支。
- 恢复工作必须核对主任务书、now、真实分支/提交和工作区；三者不一致先查证，禁止从文件名推断完成。

## 规则依据

项目采用 [通用规则入口 AGENTS.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AGENTS.md)，并配套 [ALL_AI_CODE.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/ALL_AI_CODE.md)、[AI_PROJECT_RULES.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AI_PROJECT_RULES.md)。本次读取的规则仓库提交为 `c0a57ae1b391ba48bc0b20ae9f9c71eb0926ec40`。项目专属要求与当前用户授权同时适用，不在此复制一套分叉规则。

基线只有 LICENSE 和两份脚本，无 README、docs、依赖锁、测试或 CI 配置；本轮建立所需文档，未假设其他项目的阶段编号、Figma 或验证结果适用于本仓库。

当前结论：P05-01已验收，P05-02完整Windows报告/60项指纹/42测试ID已核对通过，现场部署未验证；P04正式06已按接续指令验收收尾；P05-03已交付待Windows，原失败与现场部署待办保留。
