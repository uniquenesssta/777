# 文档与计划入口

2026-10-17已按用户“开始推进02”进入P08-02，前序已启动[P08](now/P08-cutover.md)，唯一执行分支 `stage/p08-cutover`，基线 `aca4ce3`。用户确认无历史订单，历史迁移范围为0；服务连接优先级按用户最新指令规划为192.168.4.23→192.168.4.38，封包母版设置隐藏4.23地址（已接入待Windows验证，主备切换待实现），首批母版1台。协议/身份/备份格式已按源码登记，实际主机运行账户、自启动、目录和设备映射待落实。P07按接续指令转接归档，未补造05/06单独签收或07增补Windows结果；已取消的母子构建准备验证不重新安排。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 当前阶段 / Atomic Task | [P08-02](now/P08-cutover.md)，实际主机登记待落实 |
| 唯一执行分支 / 基线 | `stage/p08-cutover` / `aca4ce3b27381abb70920f410c5ead3b1bf2a2ae` |
| 历史数据 | 用户明确没有历史订单，迁移范围0；不运行导入或补造历史对账 |
| 主机与终端 | 规划优先192.168.4.23、其次192.168.4.38；封包母版设置隐藏4.23（已接入待验证）；首批母版1台，设备主体映射待登记，子版未定 |
| 本轮交付 | [P08-02部署入口与验证](verification/P08-02-deployment.md)、[01准备登记](verification/P08-01-preparation.json)及[P08任务书](now/P08-cutover.md) |
| 原P07 | [任务书转接old](old/P07-tauri-desktop.md)，01至04原验收保持，未追加05/06/07全项验收 |
| 后续 | 先确定主备同步/接管方案，再补实际主机、账户、自启动、目录和发行清单；P08-03/04未启动，02真实部署待完成 |

[主任务书](MASTER_PLAN.md)为阶段索引，[迁移契约](MIGRATION_CONTRACT.md)为业务规则权威；根README的Change Log为唯一变更摘要。

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
- P01实际分支 `stage/p01-baseline` 以已核验的 `plans@78a1e1d` 为基线，业务源码与master原始blob一致；P02实际分支stage/p02-calculation基于P01验收提交7099303；P03实际分支stage/p03-file-safety基于P02验收提交96735ad；P04实际分支stage/p04-performance基于P03验收提交823a487；P05已按用户依赖例外授权从31c8784建立stage/p05-data-service；P06已从7710132建立stage/p06-rust-core，P07从P06收尾7a243d5建立stage/p07-tauri-desktop，P08按用户2026-10-17启动指令从P07的aca4ce3创建stage/p08-cutover，不从master重开。
- 开发分支携带当前任务书记录。需同步 plans 索引时只同步文档且核对最新状态；不要把 plans 旧代码合并回开发分支，不为了同步文档制造第二条开发分支。
- 恢复工作必须核对主任务书、now、真实分支/提交和工作区；三者不一致先查证，禁止从文件名推断完成。

## 规则依据

项目采用 [通用规则入口 AGENTS.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AGENTS.md)，并配套 [ALL_AI_CODE.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/ALL_AI_CODE.md)、[AI_PROJECT_RULES.md](https://github.com/uniquenesssta/skil/blob/main/0.0.1/AI_PROJECT_RULES.md)。本次读取的规则仓库提交为 `c0a57ae1b391ba48bc0b20ae9f9c71eb0926ec40`。项目专属要求与当前用户授权同时适用，不在此复制一套分叉规则。

基线只有 LICENSE 和两份脚本，无 README、docs、依赖锁、测试或 CI 配置；本轮建立所需文档，未假设其他项目的阶段编号、Figma 或验证结果适用于本仓库。

当前结论：P08-02执行中，P07按用户后续阶段指令转接归档，保留未验收事实。当前Figma和原功能设计仍见[映射](design/P07-component-map.md)及[P07追加任务](old/P07-tauri-desktop.md)。
